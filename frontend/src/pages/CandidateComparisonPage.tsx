import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  EyeOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Input,
  List,
  Modal,
  Progress,
  Skeleton,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { useMemo, useState, type ReactNode } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'

import {
  ApiError,
  compareScreeningResults,
  createRecruiterDecision,
  fetchJob,
  fetchOriginalEvidence,
  type AIGroup,
  type DecisionAction,
  type EvidenceCitationRecord,
  type ManualDecision,
  type OriginalEvidenceRecord,
  type RequirementStatus,
  type ScreeningResultDetail,
} from '../api/client'
import { useAuth } from '../auth/context'
import {
  canManageRecruitment,
  canViewSensitiveRecruitmentData,
} from '../auth/permissions'

const { Title, Text, Paragraph } = Typography

const aiGroupMeta: Record<AIGroup, { color: string; label: string }> = {
  passed: { color: 'success', label: '通过组' },
  low_match: { color: 'warning', label: '低匹配组' },
  auto_rejected: { color: 'error', label: '自动淘汰组' },
}

const decisionMeta: Record<ManualDecision, { color: string; label: string }> = {
  unprocessed: { color: 'default', label: '未处理' },
  shortlisted: { color: 'success', label: '入选' },
  pending: { color: 'warning', label: '待定' },
  rejected: { color: 'error', label: '人工淘汰' },
}

const requirementMeta: Record<RequirementStatus, { color: string; label: string }> = {
  passed: { color: 'success', label: '通过' },
  failed: { color: 'error', label: '不通过' },
  unknown: { color: 'warning', label: '待确认' },
}

function evidenceLocation(
  evidence: Pick<
    EvidenceCitationRecord | OriginalEvidenceRecord,
    'source_type' | 'page_number' | 'paragraph_index'
  >,
) {
  if (evidence.source_type === 'pdf_page') return `PDF 第 ${evidence.page_number ?? '-'} 页`
  if (evidence.source_type === 'docx_paragraph') {
    return `DOCX 第 ${evidence.paragraph_index ?? '-'} 段`
  }
  return '图片 OCR'
}

function TextList({ items }: { items: string[] }) {
  if (!items.length) return <Text type="secondary">暂无</Text>
  return (
    <List
      size="small"
      dataSource={items}
      renderItem={(item) => <List.Item>{item}</List.Item>}
    />
  )
}

interface ComparisonRow {
  key: string
  label: string
  render: (candidate: ScreeningResultDetail) => ReactNode
}

export function CandidateComparisonPage() {
  const { jobId } = useParams()
  const auth = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [decisionTarget, setDecisionTarget] = useState<{
    resultId: string
    aiGroup: AIGroup | null
    action: DecisionAction
  }>()
  const [decisionReason, setDecisionReason] = useState('')
  const [evidenceTarget, setEvidenceTarget] = useState<{
    resultId: string
    citationId: string
  }>()

  const resultIds = useMemo(() => {
    const value = new URLSearchParams(location.search).get('ids') ?? ''
    return [...new Set(value.split(',').map((item) => item.trim()).filter(Boolean))]
  }, [location.search])
  const selectionIsValid = resultIds.length >= 2 && resultIds.length <= 3
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
  })
  const comparison = useQuery({
    queryKey: ['candidate-comparison', jobId, resultIds],
    queryFn: () => compareScreeningResults(jobId!, resultIds),
    enabled: Boolean(jobId && selectionIsValid),
  })
  const evidence = useQuery({
    queryKey: [
      'comparison-evidence',
      jobId,
      evidenceTarget?.resultId,
      evidenceTarget?.citationId,
    ],
    queryFn: () =>
      fetchOriginalEvidence(
        jobId!,
        evidenceTarget!.resultId,
        evidenceTarget!.citationId,
      ),
    enabled: Boolean(
      jobId && evidenceTarget && canViewSensitiveRecruitmentData(auth.user),
    ),
  })
  const decisionMutation = useMutation({
    mutationFn: () =>
      createRecruiterDecision(
        jobId!,
        decisionTarget!.resultId,
        decisionTarget!.action,
        decisionReason,
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['candidate-comparison', jobId] }),
        queryClient.invalidateQueries({ queryKey: ['screening-results', jobId] }),
      ])
      messageApi.success('人工结论已保存')
      setDecisionTarget(undefined)
      setDecisionReason('')
    },
    onError: (error) =>
      messageApi.error(error instanceof ApiError ? error.message : '保存人工结论失败'),
  })

  const requiresRecoveryReason = Boolean(
    decisionTarget?.aiGroup === 'auto_rejected' &&
      ['shortlisted', 'pending'].includes(decisionTarget.action),
  )
  const canWrite =
    canManageRecruitment(auth.user) && job.data?.status !== 'archived'
  const canViewSensitive = canViewSensitiveRecruitmentData(auth.user)

  function submitDecision() {
    if (requiresRecoveryReason && !decisionReason.trim()) {
      messageApi.error('恢复自动淘汰候选人时必须填写原因')
      return
    }
    decisionMutation.mutate()
  }

  const rows = useMemo<ComparisonRow[]>(() => {
    const candidates = comparison.data?.candidates ?? []
    if (!candidates.length) return []
    const dimensionNames = candidates[0].dimension_scores.map((item) => item.dimension_name)
    const hardRequirements = candidates[0].hard_requirements.map((item) => ({
      id: item.requirement_id,
      title: item.title,
    }))
    return [
      {
        key: 'total-score',
        label: '总分',
        render: (candidate) => (
          <div className="comparison-score">
            <Progress type="circle" size={72} percent={candidate.total_score ?? 0} />
            <Text type="secondary">通过线 {candidate.pass_threshold}</Text>
          </div>
        ),
      },
      {
        key: 'ai-group',
        label: 'AI 分组',
        render: (candidate) =>
          candidate.ai_group ? (
            <Tag color={aiGroupMeta[candidate.ai_group].color}>
              {aiGroupMeta[candidate.ai_group].label}
            </Tag>
          ) : (
            '-'
          ),
      },
      {
        key: 'decision',
        label: '人工结论',
        render: (candidate) => (
          <Space direction="vertical" size="small">
            <Tag color={decisionMeta[candidate.current_decision].color}>
              {decisionMeta[candidate.current_decision].label}
            </Tag>
            {canWrite && <Space wrap size="small">
              <Button
                size="small"
                type="primary"
                icon={<CheckCircleOutlined />}
                onClick={() =>
                  setDecisionTarget({
                    resultId: candidate.id,
                    aiGroup: candidate.ai_group,
                    action: 'shortlisted',
                  })
                }
              >
                入选
              </Button>
              <Button
                size="small"
                icon={<ClockCircleOutlined />}
                onClick={() =>
                  setDecisionTarget({
                    resultId: candidate.id,
                    aiGroup: candidate.ai_group,
                    action: 'pending',
                  })
                }
              >
                待定
              </Button>
              <Button
                size="small"
                danger
                icon={<CloseCircleOutlined />}
                onClick={() =>
                  setDecisionTarget({
                    resultId: candidate.id,
                    aiGroup: candidate.ai_group,
                    action: 'rejected',
                  })
                }
              >
                淘汰
              </Button>
            </Space>}
          </Space>
        ),
      },
      ...dimensionNames.map<ComparisonRow>((name) => ({
        key: `dimension-${name}`,
        label: `评分 · ${name}`,
        render: (candidate) => {
          const item = candidate.dimension_scores.find(
            (dimension) => dimension.dimension_name === name,
          )
          if (!item) return <Text type="secondary">无该维度</Text>
          return (
            <div className="comparison-detail-cell">
              <Space>
                <Text strong className="comparison-dimension-score">{item.score}</Text>
                <Text type="secondary">权重 {item.weight_percent}%</Text>
              </Space>
              <Paragraph>{item.rationale}</Paragraph>
              {item.missing_items.length > 0 && (
                <div>{item.missing_items.map((value) => <Tag key={value} color="warning">{value}</Tag>)}</div>
              )}
              {canViewSensitive && <div className="evidence-button-list">
                {item.evidence.map((citation) => (
                  <Button
                    key={citation.id}
                    size="small"
                    icon={<EyeOutlined />}
                    onClick={() =>
                      setEvidenceTarget({ resultId: candidate.id, citationId: citation.id })
                    }
                  >
                    {citation.segment_key} · {evidenceLocation(citation)}
                  </Button>
                ))}
              </div>}
            </div>
          )
        },
      })),
      ...hardRequirements.map<ComparisonRow>((requirement) => ({
        key: `requirement-${requirement.id}`,
        label: `硬条件 · ${requirement.title}`,
        render: (candidate) => {
          const item = candidate.hard_requirements.find(
            (value) => value.requirement_id === requirement.id,
          )
          if (!item) return <Text type="secondary">无该条件</Text>
          const citations = candidate.evidence.filter(
            (citation) =>
              citation.subject_type === 'hard_requirement' &&
              citation.subject_key === requirement.id,
          )
          return (
            <div className="comparison-detail-cell">
              <Tag color={requirementMeta[item.status].color}>
                {requirementMeta[item.status].label}
              </Tag>
              <Paragraph>{item.rationale}</Paragraph>
              {canViewSensitive && <div className="evidence-button-list">
                {citations.map((citation) => (
                  <Button
                    key={citation.id}
                    size="small"
                    icon={<EyeOutlined />}
                    onClick={() =>
                      setEvidenceTarget({ resultId: candidate.id, citationId: citation.id })
                    }
                  >
                    {citation.segment_key}
                  </Button>
                ))}
              </div>}
            </div>
          )
        },
      })),
      { key: 'strengths', label: '优势', render: (candidate) => <TextList items={candidate.strengths} /> },
      { key: 'gaps', label: '差距', render: (candidate) => <TextList items={candidate.gaps} /> },
      { key: 'missing', label: '缺失项', render: (candidate) => <TextList items={candidate.missing_items} /> },
    ]
  }, [canViewSensitive, canWrite, comparison.data?.candidates])

  const columns = useMemo(() => {
    const candidates = comparison.data?.candidates ?? []
    return [
      {
        title: '对比项',
        dataIndex: 'label',
        key: 'label',
        width: 180,
        fixed: 'left' as const,
        render: (value: string) => <Text strong>{value}</Text>,
      },
      ...candidates.map((candidate) => ({
        title: (
          <Space direction="vertical" size={2}>
            <Text strong>{candidate.candidate_code}</Text>
            <Text type="secondary">总分 {candidate.total_score?.toFixed(1) ?? '-'}</Text>
          </Space>
        ),
        key: candidate.id,
        width: 300,
        render: (_: unknown, row: ComparisonRow) => row.render(candidate),
      })),
    ]
  }, [comparison.data?.candidates])

  if (job.isPending) return <Skeleton active paragraph={{ rows: 10 }} />
  if (job.isError || !job.data) {
    return <Alert type="error" showIcon message="无法读取职位" description={job.error?.message} />
  }

  return (
    <>
      {contextHolder}
      <div className="page-heading">
        <div>
          <Title level={2}>候选人横向对比</Title>
          <Text type="secondary">{job.data.title} · 同一标准下最多比较 3 名候选人</Text>
        </div>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/jobs/${jobId}/results`)}>
          返回筛选结果
        </Button>
      </div>

      {!selectionIsValid && (
        <Alert
          type="warning"
          showIcon
          message="请选择 2～3 名候选人"
          description="候选人数量不能少于 2 名或超过 3 名。"
          action={<Button onClick={() => navigate(`/jobs/${jobId}/results`)}>重新选择</Button>}
        />
      )}
      {comparison.isPending && selectionIsValid && <Skeleton active paragraph={{ rows: 14 }} />}
      {comparison.isError && (
        <Alert
          type="error"
          showIcon
          message="无法比较候选人"
          description={comparison.error.message}
          action={<Button onClick={() => navigate(`/jobs/${jobId}/results`)}>重新选择</Button>}
        />
      )}
      {comparison.isSuccess && comparison.data.candidates.length === 0 && (
        <Empty description="没有可比较的候选人" />
      )}
      {comparison.isSuccess && comparison.data.candidates.length > 0 && (
        <>
          <Card className="comparison-meta-card">
            <Descriptions
              size="small"
              column={3}
              items={[
                { key: 'count', label: '候选人数', children: comparison.data.candidates.length },
                { key: 'criteria', label: '职位标准', children: `V${comparison.data.criteria_version_number}` },
                { key: 'analysis', label: '分析版本', children: `V${comparison.data.analysis_version}` },
              ]}
            />
          </Card>
          <Card className="comparison-table-card">
            <Table<ComparisonRow>
              rowKey="key"
              columns={columns}
              dataSource={rows}
              pagination={false}
              scroll={{ x: 180 + comparison.data.candidates.length * 300 }}
            />
          </Card>
        </>
      )}

      {canWrite && <Modal
        title={`保存人工结论：${decisionTarget ? decisionMeta[decisionTarget.action].label : ''}`}
        open={Boolean(decisionTarget)}
        okText="保存结论"
        cancelText="取消"
        confirmLoading={decisionMutation.isPending}
        onOk={submitDecision}
        onCancel={() => {
          setDecisionTarget(undefined)
          setDecisionReason('')
        }}
      >
        {requiresRecoveryReason && (
          <Alert
            type="warning"
            showIcon
            message="恢复自动淘汰候选人时必须填写原因"
            className="decision-warning"
          />
        )}
        <label htmlFor="comparison-decision-reason">
          决策原因{requiresRecoveryReason ? '（必填）' : '（选填）'}
        </label>
        <Input.TextArea
          id="comparison-decision-reason"
          rows={4}
          maxLength={2000}
          showCount
          value={decisionReason}
          onChange={(event) => setDecisionReason(event.target.value)}
        />
      </Modal>}

      {canViewSensitive && <Modal
        title={evidence.data ? `${evidence.data.segment_key} · 授权原文证据` : '授权原文证据'}
        open={Boolean(evidenceTarget)}
        footer={null}
        width={720}
        onCancel={() => setEvidenceTarget(undefined)}
      >
        {evidence.isPending && <Skeleton active paragraph={{ rows: 6 }} />}
        {evidence.isError && <Alert type="error" showIcon message={evidence.error.message} />}
        {evidence.isSuccess && (
          <div className="original-evidence-panel">
            <Descriptions
              size="small"
              column={2}
              items={[
                { key: 'location', label: '位置', children: evidenceLocation(evidence.data) },
                { key: 'segment', label: '片段编号', children: evidence.data.segment_key },
              ]}
            />
            <Text type="secondary">AI 引用</Text>
            <blockquote>{evidence.data.quote}</blockquote>
            <Text type="secondary">授权原文片段</Text>
            <pre>{evidence.data.original_text}</pre>
          </div>
        )}
      </Modal>}
    </>
  )
}
