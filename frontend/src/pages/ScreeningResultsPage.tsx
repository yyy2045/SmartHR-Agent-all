import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  EyeOutlined,
  FileSearchOutlined,
  ReloadOutlined,
  SwapOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Progress,
  Row,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  ApiError,
  createRecruiterDecision,
  fetchJob,
  fetchOriginalEvidence,
  fetchScreeningResult,
  fetchScreeningResults,
  type AIGroup,
  type AnalysisStatus,
  type DecisionAction,
  type EvidenceCitationRecord,
  type ManualDecision,
  type RequirementStatus,
  type ScreeningResultFilters,
  type ScreeningResultSummary,
} from '../api/client'
import { ScreeningModuleNav } from '../components/ScreeningModuleNav'

const { Title, Text, Paragraph } = Typography

const analysisStatusMeta: Record<AnalysisStatus, { color: string; label: string }> = {
  processing: { color: 'processing', label: '分析中' },
  completed: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '分析失败' },
}

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

function formatDate(value: string | null) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function evidenceLocation(
  citation: Pick<
    EvidenceCitationRecord,
    'source_type' | 'page_number' | 'paragraph_index'
  >,
) {
  if (citation.source_type === 'pdf_page') return `PDF 第 ${citation.page_number ?? '-'} 页`
  if (citation.source_type === 'docx_paragraph') {
    return `DOCX 第 ${citation.paragraph_index ?? '-'} 段`
  }
  return '图片 OCR'
}

function TextItems({ title, items, tone }: { title: string; items: string[]; tone?: string }) {
  return (
    <Card className={`result-insight-card${tone ? ` is-${tone}` : ''}`} title={title} size="small">
      {items.length ? (
        <List
          size="small"
          dataSource={items}
          renderItem={(item) => <List.Item>{item}</List.Item>}
        />
      ) : (
        <Text type="secondary">暂无</Text>
      )}
    </Card>
  )
}

export function ScreeningResultsPage() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [processingStatus, setProcessingStatus] = useState<AnalysisStatus>()
  const [aiGroup, setAIGroup] = useState<AIGroup>()
  const [decision, setDecision] = useState<ManualDecision>()
  const [minScore, setMinScore] = useState<number>()
  const [maxScore, setMaxScore] = useState<number>()
  const [selectedResultId, setSelectedResultId] = useState<string>()
  const [selectedResultIds, setSelectedResultIds] = useState<string[]>([])
  const [decisionAction, setDecisionAction] = useState<DecisionAction>()
  const [decisionReason, setDecisionReason] = useState('')
  const [evidenceTarget, setEvidenceTarget] = useState<{
    resultId: string
    citationId: string
  }>()

  const filters = useMemo<ScreeningResultFilters>(
    () => ({ processingStatus, aiGroup, decision, minScore, maxScore }),
    [aiGroup, decision, maxScore, minScore, processingStatus],
  )
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
  })
  const results = useQuery({
    queryKey: [
      'screening-results',
      jobId,
      processingStatus,
      aiGroup,
      decision,
      minScore,
      maxScore,
    ],
    queryFn: () => fetchScreeningResults(jobId!, filters),
    enabled: Boolean(jobId),
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.status === 'processing') ? 3000 : false,
  })
  const detail = useQuery({
    queryKey: ['screening-result', jobId, selectedResultId],
    queryFn: () => fetchScreeningResult(jobId!, selectedResultId!),
    enabled: Boolean(jobId && selectedResultId),
  })
  const evidence = useQuery({
    queryKey: [
      'screening-evidence',
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
    enabled: Boolean(jobId && evidenceTarget),
  })
  const decisionMutation = useMutation({
    mutationFn: () =>
      createRecruiterDecision(
        jobId!,
        selectedResultId!,
        decisionAction!,
        decisionReason,
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['screening-results', jobId] }),
        queryClient.invalidateQueries({
          queryKey: ['screening-result', jobId, selectedResultId],
        }),
      ])
      messageApi.success('人工结论已保存并记录变更历史')
      setDecisionAction(undefined)
      setDecisionReason('')
    },
    onError: (error) =>
      messageApi.error(error instanceof ApiError ? error.message : '保存人工结论失败'),
  })

  const requiresRecoveryReason = Boolean(
    detail.data?.ai_group === 'auto_rejected' &&
      decisionAction &&
      ['shortlisted', 'pending'].includes(decisionAction),
  )
  const selectedSummaries = useMemo(
    () =>
      selectedResultIds.flatMap((id) => {
        const result = results.data?.find((item) => item.id === id)
        return result ? [result] : []
      }),
    [results.data, selectedResultIds],
  )

  useEffect(() => {
    if (!results.data) return
    const visibleIds = new Set(results.data.map((item) => item.id))
    setSelectedResultIds((current) => current.filter((id) => visibleIds.has(id)))
  }, [results.data])

  function openDecision(action: DecisionAction) {
    setDecisionAction(action)
    setDecisionReason('')
  }

  function submitDecision() {
    if (requiresRecoveryReason && !decisionReason.trim()) {
      messageApi.error('恢复自动淘汰候选人时必须填写原因')
      return
    }
    decisionMutation.mutate()
  }

  function clearFilters() {
    setProcessingStatus(undefined)
    setAIGroup(undefined)
    setDecision(undefined)
    setMinScore(undefined)
    setMaxScore(undefined)
  }

  function toggleComparisonCandidate(record: ScreeningResultSummary, selected: boolean) {
    if (!selected) {
      setSelectedResultIds((current) => current.filter((id) => id !== record.id))
      return
    }
    if (record.status !== 'completed') {
      messageApi.warning('只能比较已完成 AI 分析的候选人')
      return
    }
    const first = selectedSummaries[0]
    if (
      first &&
      (first.criteria_version_id !== record.criteria_version_id ||
        first.analysis_version !== record.analysis_version)
    ) {
      messageApi.warning('只能比较同一职位标准和同一分析版本的候选人')
      return
    }
    if (selectedResultIds.length >= 3) {
      messageApi.warning('一次最多比较 3 名候选人')
      return
    }
    setSelectedResultIds((current) => [...current, record.id])
  }

  const columns = [
    {
      title: '候选人',
      key: 'candidate',
      render: (_: unknown, record: ScreeningResultSummary) => (
        <Space direction="vertical" size={2}>
          <Text strong>{record.candidate_code}</Text>
          <Text type="secondary">{record.batch_name}</Text>
        </Space>
      ),
    },
    {
      title: '分析版本',
      key: 'version',
      render: (_: unknown, record: ScreeningResultSummary) => (
        <Space direction="vertical" size={2}>
          <Text>标准 V{record.criteria_version_number}</Text>
          <Text type="secondary">分析 V{record.analysis_version}</Text>
        </Space>
      ),
    },
    {
      title: '处理状态',
      dataIndex: 'status',
      key: 'status',
      render: (value: AnalysisStatus) => (
        <Tag color={analysisStatusMeta[value].color}>{analysisStatusMeta[value].label}</Tag>
      ),
    },
    {
      title: 'AI 分组',
      dataIndex: 'ai_group',
      key: 'ai_group',
      render: (value: AIGroup | null) =>
        value ? <Tag color={aiGroupMeta[value].color}>{aiGroupMeta[value].label}</Tag> : '-',
    },
    {
      title: '总分',
      dataIndex: 'total_score',
      key: 'total_score',
      render: (value: number | null, record: ScreeningResultSummary) =>
        value === null ? (
          '-'
        ) : (
          <Space direction="vertical" size={0}>
            <Text strong className="result-score-text">
              {value.toFixed(1)}
            </Text>
            <Text type="secondary">通过线 {record.pass_threshold}</Text>
          </Space>
        ),
    },
    {
      title: '人工结论',
      dataIndex: 'current_decision',
      key: 'decision',
      render: (value: ManualDecision) => (
        <Tag color={decisionMeta[value].color}>{decisionMeta[value].label}</Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, record: ScreeningResultSummary) => (
        <Button type="link" icon={<EyeOutlined />} onClick={() => setSelectedResultId(record.id)}>
          查看依据
        </Button>
      ),
    },
  ]

  if (job.isPending) return <Skeleton active paragraph={{ rows: 10 }} />
  if (job.isError || !job.data) {
    return (
      <Alert
        type="error"
        showIcon
        message="无法读取职位"
        description={job.error?.message}
        action={<Button onClick={() => void job.refetch()}>重试</Button>}
      />
    )
  }

  return (
    <>
      {contextHolder}
      <div className="page-heading">
        <div>
          <Space wrap size="small">
            <Title level={2}>{job.data.title}</Title>
            {job.data.status === 'archived' && <Tag>已归档</Tag>}
          </Space>
          <Text type="secondary">查看 AI 匹配依据，并保存最终人工筛选结论</Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => void results.refetch()}>
          刷新结果
        </Button>
      </div>

      <ScreeningModuleNav jobId={jobId} activeKey="results" />

      <Card className="result-filter-card" title="筛选条件">
        <div className="result-filter-grid">
          <Select
            aria-label="处理状态"
            allowClear
            placeholder="处理状态"
            value={processingStatus}
            onChange={setProcessingStatus}
            options={Object.entries(analysisStatusMeta).map(([value, meta]) => ({
              value,
              label: meta.label,
            }))}
          />
          <Select
            aria-label="AI 分组"
            allowClear
            placeholder="AI 分组"
            value={aiGroup}
            onChange={setAIGroup}
            options={Object.entries(aiGroupMeta).map(([value, meta]) => ({
              value,
              label: meta.label,
            }))}
          />
          <Select
            aria-label="人工结论"
            allowClear
            placeholder="人工结论"
            value={decision}
            onChange={setDecision}
            options={Object.entries(decisionMeta).map(([value, meta]) => ({
              value,
              label: meta.label,
            }))}
          />
          <InputNumber
            aria-label="最低分"
            min={0}
            max={100}
            placeholder="最低分"
            value={minScore}
            onChange={(value) => setMinScore(value ?? undefined)}
          />
          <InputNumber
            aria-label="最高分"
            min={0}
            max={100}
            placeholder="最高分"
            value={maxScore}
            onChange={(value) => setMaxScore(value ?? undefined)}
          />
          <Button onClick={clearFilters}>清空筛选</Button>
        </div>
      </Card>

      <Card
        className="result-table-card"
        title={
          <Space direction="vertical" size={0}>
            <Text strong>候选人结果</Text>
            <Text type="secondary">请选择 2～3 名同版本候选人进行横向比较</Text>
          </Space>
        }
        extra={
          <Button
            type="primary"
            icon={<SwapOutlined />}
            disabled={selectedResultIds.length < 2}
            onClick={() =>
              navigate(
                `/jobs/${jobId}/compare?ids=${encodeURIComponent(selectedResultIds.join(','))}`,
              )
            }
          >
            对比候选人（{selectedResultIds.length}/3）
          </Button>
        }
      >
        {results.isError && (
          <Alert
            type="error"
            showIcon
            message="无法读取筛选结果"
            description={results.error.message}
            action={<Button onClick={() => void results.refetch()}>重试</Button>}
          />
        )}
        {results.isLoading && <Skeleton active paragraph={{ rows: 8 }} />}
        {results.isSuccess && results.data.length === 0 && (
          <Empty
            image={<FileSearchOutlined className="empty-icon" />}
            description="当前条件下没有筛选结果"
          >
            <Button onClick={() => navigate(`/jobs/${jobId}/batches`)}>前往简历批次</Button>
          </Empty>
        )}
        {results.isSuccess && results.data.length > 0 && (
          <Table<ScreeningResultSummary>
            rowKey="id"
            columns={columns}
            dataSource={results.data}
            pagination={false}
            scroll={{ x: 960 }}
            rowSelection={{
              selectedRowKeys: selectedResultIds,
              hideSelectAll: true,
              onSelect: toggleComparisonCandidate,
              getCheckboxProps: (record) => {
                const first = selectedSummaries[0]
                const incompatible = Boolean(
                  first &&
                    first.id !== record.id &&
                    (first.criteria_version_id !== record.criteria_version_id ||
                      first.analysis_version !== record.analysis_version),
                )
                const atLimit =
                  selectedResultIds.length >= 3 && !selectedResultIds.includes(record.id)
                return {
                  disabled: record.status !== 'completed' || incompatible || atLimit,
                  title:
                    record.status !== 'completed'
                      ? '只能比较已完成分析的候选人'
                      : incompatible
                        ? '职位标准或分析版本不同'
                        : atLimit
                          ? '一次最多比较 3 名候选人'
                          : undefined,
                }
              },
            }}
          />
        )}
      </Card>

      <Drawer
        className="screening-result-drawer"
        width={900}
        open={Boolean(selectedResultId)}
        title={detail.data ? `候选人 ${detail.data.candidate_code} · 筛选依据` : '筛选依据'}
        onClose={() => setSelectedResultId(undefined)}
      >
        {detail.isPending && <Skeleton active paragraph={{ rows: 12 }} />}
        {detail.isError && (
          <Alert
            type="error"
            showIcon
            message="无法读取筛选详情"
            description={detail.error.message}
            action={<Button onClick={() => void detail.refetch()}>重试</Button>}
          />
        )}
        {detail.isSuccess && (
          <div className="result-detail-layout">
            <Card className="result-overview-card">
              <div className="result-overview">
                <Progress
                  type="circle"
                  percent={detail.data.total_score ?? 0}
                  format={(value) => (detail.data.total_score === null ? '-' : `${value}`)}
                  strokeColor={detail.data.ai_group === 'auto_rejected' ? '#d04444' : '#2477d4'}
                />
                <Descriptions
                  column={2}
                  size="small"
                  items={[
                    {
                      key: 'status',
                      label: '处理状态',
                      children: (
                        <Tag color={analysisStatusMeta[detail.data.status].color}>
                          {analysisStatusMeta[detail.data.status].label}
                        </Tag>
                      ),
                    },
                    {
                      key: 'group',
                      label: 'AI 分组',
                      children: detail.data.ai_group ? (
                        <Tag color={aiGroupMeta[detail.data.ai_group].color}>
                          {aiGroupMeta[detail.data.ai_group].label}
                        </Tag>
                      ) : (
                        '-'
                      ),
                    },
                    {
                      key: 'decision',
                      label: '人工结论',
                      children: (
                        <Tag color={decisionMeta[detail.data.current_decision].color}>
                          {decisionMeta[detail.data.current_decision].label}
                        </Tag>
                      ),
                    },
                    {
                      key: 'version',
                      label: '分析版本',
                      children: `标准 V${detail.data.criteria_version_number} / 分析 V${detail.data.analysis_version}`,
                    },
                    {
                      key: 'threshold',
                      label: '通过线',
                      children: detail.data.pass_threshold,
                    },
                    {
                      key: 'completed',
                      label: '完成时间',
                      children: formatDate(detail.data.completed_at),
                    },
                  ]}
                />
              </div>
              {detail.data.status === 'failed' && (
                <Alert
                  type="error"
                  showIcon
                  message={detail.data.failure_message ?? 'AI 分析失败'}
                />
              )}
            </Card>

            <section>
              <Title level={4}>分维度评分</Title>
              <div className="dimension-result-list">
                {detail.data.dimension_scores.map((item) => (
                  <Card key={item.id} size="small" className="dimension-result-card">
                    <div className="dimension-result-heading">
                      <div>
                        <Text strong>{item.dimension_name}</Text>
                        <Text type="secondary">权重 {item.weight_percent}% · 贡献 {item.weighted_score.toFixed(2)}</Text>
                      </div>
                      <Progress type="circle" size={58} percent={item.score} />
                    </div>
                    <Paragraph>{item.rationale}</Paragraph>
                    {item.missing_items.length > 0 && (
                      <div className="result-tag-row">
                        <Text type="secondary">缺失：</Text>
                        {item.missing_items.map((missing) => (
                          <Tag key={missing} color="warning">{missing}</Tag>
                        ))}
                      </div>
                    )}
                    <div className="evidence-button-list">
                      {item.evidence.map((citation) => (
                        <Button
                          key={citation.id}
                          size="small"
                          icon={<EyeOutlined />}
                          onClick={() =>
                            setEvidenceTarget({ resultId: detail.data.id, citationId: citation.id })
                          }
                        >
                          {citation.segment_key} · {evidenceLocation(citation)}
                        </Button>
                      ))}
                    </div>
                  </Card>
                ))}
              </div>
            </section>

            <section>
              <Title level={4}>硬性条件</Title>
              <List
                className="hard-requirement-result-list"
                dataSource={detail.data.hard_requirements}
                locale={{ emptyText: '该职位未配置硬性条件' }}
                renderItem={(item) => {
                  const citations = detail.data.evidence.filter(
                    (citation) =>
                      citation.subject_type === 'hard_requirement' &&
                      citation.subject_key === item.requirement_id,
                  )
                  return (
                    <List.Item>
                      <div className="hard-requirement-result">
                        <div>
                          <Space wrap>
                            <Text strong>{item.title}</Text>
                            <Tag color={requirementMeta[item.status].color}>
                              {requirementMeta[item.status].label}
                            </Tag>
                            {item.auto_reject && <Tag>允许自动淘汰</Tag>}
                          </Space>
                          <Paragraph>{item.rationale}</Paragraph>
                          <Text type="secondary">期望：{item.expected_value}</Text>
                        </div>
                        <div className="evidence-button-list">
                          {citations.map((citation) => (
                            <Button
                              key={citation.id}
                              size="small"
                              icon={<EyeOutlined />}
                              onClick={() =>
                                setEvidenceTarget({
                                  resultId: detail.data.id,
                                  citationId: citation.id,
                                })
                              }
                            >
                              {citation.segment_key}
                            </Button>
                          ))}
                        </div>
                      </div>
                    </List.Item>
                  )
                }}
              />
            </section>

            <Row gutter={[14, 14]}>
              <Col xs={24} md={12}><TextItems title="优势" items={detail.data.strengths} tone="success" /></Col>
              <Col xs={24} md={12}><TextItems title="差距" items={detail.data.gaps} tone="danger" /></Col>
              <Col xs={24} md={12}><TextItems title="信息缺失" items={detail.data.missing_items} tone="warning" /></Col>
              <Col xs={24} md={12}><TextItems title="面试核实建议" items={detail.data.interview_questions} tone="info" /></Col>
            </Row>

            <Card title="人工决策" className="decision-panel">
              <Space wrap>
                <Button
                  type="primary"
                  icon={<CheckCircleOutlined />}
                  disabled={detail.data.status !== 'completed'}
                  onClick={() => openDecision('shortlisted')}
                >
                  标记入选
                </Button>
                <Button
                  icon={<ClockCircleOutlined />}
                  disabled={detail.data.status !== 'completed'}
                  onClick={() => openDecision('pending')}
                >
                  标记待定
                </Button>
                <Button
                  danger
                  icon={<CloseCircleOutlined />}
                  disabled={detail.data.status !== 'completed'}
                  onClick={() => openDecision('rejected')}
                >
                  人工淘汰
                </Button>
              </Space>
              <Timeline
                className="decision-timeline"
                items={detail.data.decision_history.map((item) => ({
                  color: decisionMeta[item.decision].color,
                  children: (
                    <div>
                      <Space wrap>
                        <Text strong>
                          {decisionMeta[item.previous_decision].label} → {decisionMeta[item.decision].label}
                        </Text>
                        {item.is_auto_rejection_override && <Tag color="warning">恢复自动淘汰</Tag>}
                      </Space>
                      <div><Text type="secondary">{item.operator_display_name} · {formatDate(item.created_at)}</Text></div>
                      {item.reason && <Paragraph>{item.reason}</Paragraph>}
                    </div>
                  ),
                }))}
                pending={detail.data.decision_history.length ? undefined : '尚未作出人工结论'}
              />
            </Card>
          </div>
        )}
      </Drawer>

      <Modal
        title={`保存人工结论：${decisionAction ? decisionMeta[decisionAction].label : ''}`}
        open={Boolean(decisionAction)}
        okText="保存结论"
        cancelText="取消"
        confirmLoading={decisionMutation.isPending}
        onOk={submitDecision}
        onCancel={() => {
          setDecisionAction(undefined)
          setDecisionReason('')
        }}
      >
        {requiresRecoveryReason && (
          <Alert
            type="warning"
            showIcon
            message="该候选人由硬性条件自动淘汰，恢复时必须填写原因"
            className="decision-warning"
          />
        )}
        <label htmlFor="decision-reason">
          决策原因{requiresRecoveryReason ? '（必填）' : '（选填）'}
        </label>
        <Input.TextArea
          id="decision-reason"
          value={decisionReason}
          maxLength={2000}
          showCount
          rows={4}
          placeholder="说明判断依据或需要后续核实的事项"
          onChange={(event) => setDecisionReason(event.target.value)}
        />
      </Modal>

      <Modal
        title={evidence.data ? `${evidence.data.segment_key} · 授权原文证据` : '授权原文证据'}
        open={Boolean(evidenceTarget)}
        footer={null}
        width={720}
        onCancel={() => setEvidenceTarget(undefined)}
      >
        {evidence.isPending && <Skeleton active paragraph={{ rows: 6 }} />}
        {evidence.isError && (
          <Alert
            type="error"
            showIcon
            message="无法读取原文证据"
            description={evidence.error.message}
          />
        )}
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
            <Text type="secondary">已登录招聘专员可查看的原文片段</Text>
            <pre>{evidence.data.original_text}</pre>
          </div>
        )}
      </Modal>
    </>
  )
}
