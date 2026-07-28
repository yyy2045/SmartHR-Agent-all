import {
  ArrowLeftOutlined,
  CheckOutlined,
  DeleteOutlined,
  DollarOutlined,
  FileTextOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Collapse,
  Empty,
  Input,
  Modal,
  Radio,
  Skeleton,
  Space,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  ApiError,
  confirmInterviewReport,
  createInterviewReportVersion,
  createManualInterviewReport,
  fetchInterviewReport,
  fetchInterviewReportContext,
  fetchJob,
  generateAIInterviewReport,
  type InterviewReportConclusion,
  type InterviewReportContent,
  type InterviewReportContext,
  type InterviewReportRecord,
  type InterviewReportVersion,
} from '../api/client'
import { useAuth } from '../auth/context'
import { canManageRecruitment } from '../auth/permissions'
import { InterviewModuleNav } from '../components/InterviewModuleNav'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

const conclusionMeta: Record<
  InterviewReportConclusion,
  { label: string; color: string }
> = {
  hire: { label: '录用', color: 'success' },
  next_round: { label: '下一轮', color: 'processing' },
  reserve: { label: '保留', color: 'warning' },
  reject: { label: '淘汰', color: 'error' },
}

const emptyContent: InterviewReportContent = {
  conclusion: null,
  executive_summary: '',
  strengths: [],
  concerns: [],
  follow_up_actions: [],
}

function formatDateTime(value: string | null): string {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function contentFromVersion(version: InterviewReportVersion): InterviewReportContent {
  return {
    conclusion: version.conclusion,
    executive_summary: version.executive_summary,
    strengths: [...version.strengths],
    concerns: [...version.concerns],
    follow_up_actions: [...version.follow_up_actions],
  }
}

function normalizedContent(content: InterviewReportContent): InterviewReportContent {
  return {
    conclusion: content.conclusion,
    executive_summary: content.executive_summary.trim(),
    strengths: content.strengths.map((item) => item.trim()).filter(Boolean),
    concerns: content.concerns.map((item) => item.trim()).filter(Boolean),
    follow_up_actions: content.follow_up_actions.map((item) => item.trim()).filter(Boolean),
  }
}

function isSameContent(
  left: InterviewReportContent,
  right: InterviewReportContent,
): boolean {
  return JSON.stringify(normalizedContent(left)) === JSON.stringify(normalizedContent(right))
}

function newIdempotencyKey(): string {
  return crypto.randomUUID()
}

function DynamicTextList({
  title,
  placeholder,
  values,
  disabled,
  onChange,
}: {
  title: string
  placeholder: string
  values: string[]
  disabled: boolean
  onChange: (values: string[]) => void
}) {
  return (
    <section className="report-list-field">
      <div className="report-list-field-heading">
        <Text strong>{title}</Text>
        {!disabled && (
          <Button
            type="text"
            size="small"
            icon={<PlusOutlined />}
            onClick={() => onChange([...values, ''])}
          >
            添加
          </Button>
        )}
      </div>
      {values.length === 0 ? (
        <Text type="secondary">暂无内容</Text>
      ) : (
        <Space direction="vertical" size="small" className="report-list-field-items">
          {values.map((value, index) => (
            <div className="report-list-field-row" key={`${title}-${index}`}>
              <Input
                aria-label={`${title} ${index + 1}`}
                value={value}
                disabled={disabled}
                maxLength={1000}
                placeholder={placeholder}
                onChange={(event) => {
                  const next = [...values]
                  next[index] = event.target.value
                  onChange(next)
                }}
              />
              {!disabled && (
                <Tooltip title="删除">
                  <Button
                    aria-label={`删除${title} ${index + 1}`}
                    icon={<DeleteOutlined />}
                    onClick={() => onChange(values.filter((_, itemIndex) => itemIndex !== index))}
                  />
                </Tooltip>
              )}
            </div>
          ))}
        </Space>
      )}
    </section>
  )
}

function ReportContentEditor({
  value,
  disabled,
  onChange,
}: {
  value: InterviewReportContent
  disabled: boolean
  onChange: (value: InterviewReportContent) => void
}) {
  return (
    <div className="report-editor">
      <section className="report-editor-section">
        <Text strong>报告结论</Text>
        <Radio.Group
          className="report-conclusion-control"
          optionType="button"
          buttonStyle="solid"
          value={value.conclusion}
          disabled={disabled}
          options={Object.entries(conclusionMeta).map(([key, meta]) => ({
            value: key,
            label: meta.label,
          }))}
          onChange={(event) => onChange({ ...value, conclusion: event.target.value })}
        />
      </section>
      <section className="report-editor-section">
        <Text strong>执行摘要</Text>
        <TextArea
          aria-label="执行摘要"
          rows={6}
          value={value.executive_summary}
          disabled={disabled}
          maxLength={5000}
          showCount={!disabled}
          placeholder="汇总候选人与岗位匹配结论及关键依据"
          onChange={(event) => onChange({ ...value, executive_summary: event.target.value })}
        />
      </section>
      <div className="report-editor-list-grid">
        <DynamicTextList
          title="主要优势"
          placeholder="填写有证据支持的优势"
          values={value.strengths}
          disabled={disabled}
          onChange={(strengths) => onChange({ ...value, strengths })}
        />
        <DynamicTextList
          title="风险与疑点"
          placeholder="填写需要关注或核实的事项"
          values={value.concerns}
          disabled={disabled}
          onChange={(concerns) => onChange({ ...value, concerns })}
        />
      </div>
      <DynamicTextList
        title="后续动作"
        placeholder="填写明确的下一步安排"
        values={value.follow_up_actions}
        disabled={disabled}
        onChange={(follow_up_actions) => onChange({ ...value, follow_up_actions })}
      />
    </div>
  )
}

function EvidenceView({ context }: { context: InterviewReportContext }) {
  const screening = context.latest_screening
  return (
    <div className="report-evidence">
      <section className="report-evidence-overview" aria-label="证据概览">
        <div>
          <Text type="secondary">筛选结果</Text>
          <strong>{screening ? `${screening.total_score?.toFixed(1) ?? '-'} 分` : '无'}</strong>
        </div>
        <div>
          <Text type="secondary">已提交评价</Text>
          <strong>{context.submitted_evaluations.length}</strong>
        </div>
        <div>
          <Text type="secondary">缺失轮次</Text>
          <strong>{context.missing_rounds.length}</strong>
        </div>
      </section>

      <section className="report-evidence-section">
        <div className="report-section-heading">
          <Title level={4}>最新筛选结果</Title>
          {screening && <Tag color="blue">分析 V{screening.analysis_version}</Tag>}
        </div>
        {!screening ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有已完成的筛选结果" />
        ) : (
          <>
            <Space wrap>
              <Tag color={screening.current_decision === 'shortlisted' ? 'success' : 'default'}>
                人工结论：{screening.current_decision === 'shortlisted' ? '通过' : screening.current_decision === 'pending' ? '待定' : screening.current_decision === 'rejected' ? '淘汰' : '未处理'}
              </Tag>
              <Text type="secondary">通过线 {screening.pass_threshold} 分</Text>
              <Text type="secondary">{formatDateTime(screening.completed_at)}</Text>
            </Space>
            <div className="report-screening-grid">
              <div><Text strong>优势</Text><Paragraph>{screening.strengths.join('；') || '无'}</Paragraph></div>
              <div><Text strong>差距</Text><Paragraph>{screening.gaps.join('；') || '无'}</Paragraph></div>
              <div><Text strong>缺失项</Text><Paragraph>{screening.missing_items.join('；') || '无'}</Paragraph></div>
            </div>
            {screening.citations.length > 0 && (
              <div className="report-citation-list">
                <Text strong>筛选证据引用</Text>
                {screening.citations.map((citation) => (
                  <blockquote key={citation.id}>{citation.quote}</blockquote>
                ))}
              </div>
            )}
          </>
        )}
      </section>

      <section className="report-evidence-section">
        <div className="report-section-heading">
          <Title level={4}>已提交面试评价</Title>
          <Tag>{context.submitted_evaluations.length} 轮</Tag>
        </div>
        {context.submitted_evaluations.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无已提交评价" />
        ) : (
          <Collapse
            items={context.submitted_evaluations.map((evaluation) => ({
              key: evaluation.evaluation_id,
              label: (
                <Space wrap>
                  <Text strong>{evaluation.round_name}</Text>
                  <Tag color={evaluation.passed ? 'success' : evaluation.passed === false ? 'error' : 'default'}>
                    {evaluation.total_score === null ? '未计算分数' : `${evaluation.total_score.toFixed(1)} 分`}
                  </Tag>
                  <Text type="secondary">{formatDateTime(evaluation.submitted_at)}</Text>
                </Space>
              ),
              children: (
                <div className="report-evaluation-evidence">
                  <Paragraph>{evaluation.overall_comment || '未填写总体评价'}</Paragraph>
                  {evaluation.dimension_ratings.map((rating) => (
                    <div key={rating.dimension_id}>
                      <Text strong>{rating.dimension_name} · {rating.score ?? '-'} 分</Text>
                      <Paragraph type="secondary">{rating.evidence || '未填写评分依据'}</Paragraph>
                    </div>
                  ))}
                  {evaluation.question_responses.map((response) => (
                    <div key={response.question_id}>
                      <Text strong>{response.question_text}</Text>
                      <Paragraph>{response.answer_summary}</Paragraph>
                      <blockquote>{response.evidence}</blockquote>
                    </div>
                  ))}
                </div>
              ),
            }))}
          />
        )}
      </section>

      {context.missing_rounds.length > 0 && (
        <section className="report-evidence-section">
          <div className="report-section-heading"><Title level={4}>缺失轮次</Title></div>
          <Space wrap>
            {context.missing_rounds.map((round) => (
              <Tag key={round.round_id} color={round.reason === 'cancelled' ? 'default' : 'warning'}>
                {round.round_name} · {round.reason === 'cancelled' ? '已取消' : '评价未提交'}
              </Tag>
            ))}
          </Space>
        </section>
      )}
    </div>
  )
}

export function InterviewReportPage() {
  const { jobId, applicationId } = useParams()
  const auth = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [selectedVersionId, setSelectedVersionId] = useState<string>()
  const [draft, setDraft] = useState<InterviewReportContent>(emptyContent)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
  })
  const context = useQuery({
    queryKey: ['interview-report-context', jobId, applicationId],
    queryFn: () => fetchInterviewReportContext(jobId!, applicationId!),
    enabled: Boolean(jobId && applicationId),
  })
  const report = useQuery({
    queryKey: ['interview-report', jobId, applicationId],
    queryFn: () => fetchInterviewReport(jobId!, applicationId!),
    enabled: Boolean(jobId && applicationId),
  })
  const currentVersion = report.data?.versions.find(
    (version) => version.version_number === report.data?.current_version_number,
  )
  const selectedVersion =
    report.data?.versions.find((version) => version.id === selectedVersionId) ??
    currentVersion

  useEffect(() => {
    if (!currentVersion) return
    setSelectedVersionId(currentVersion.id)
    setDraft(contentFromVersion(currentVersion))
  }, [currentVersion])

  const archived = job.data?.status === 'archived'
  const merged = context.data?.application_status === 'merged'
  const roleReadOnly = !canManageRecruitment(auth.user)
  const reportLocked = report.data?.status === 'confirmed'
  const viewingHistory = Boolean(
    selectedVersion && currentVersion && selectedVersion.id !== currentVersion.id,
  )
  const readOnly = Boolean(roleReadOnly || archived || merged || reportLocked || viewingHistory)
  const contentDirty = Boolean(
    currentVersion && !isSameContent(draft, contentFromVersion(currentVersion)),
  )
  const pageError = job.error ?? context.error ?? report.error
  const loading = job.isPending || context.isPending || report.isPending

  function updateReportCache(result: InterviewReportRecord) {
    queryClient.setQueryData(['interview-report', jobId, applicationId], result)
    void queryClient.invalidateQueries({ queryKey: ['interview-reports', jobId] })
  }

  const manualMutation = useMutation({
    mutationFn: () =>
      createManualInterviewReport(
        jobId!,
        applicationId!,
        newIdempotencyKey(),
        emptyContent,
      ),
    onSuccess: (result) => {
      updateReportCache(result)
      void messageApi.success('已创建人工面试报告草稿')
    },
    onError: (error) =>
      void messageApi.error(error instanceof Error ? error.message : '创建报告失败'),
  })
  const aiMutation = useMutation({
    mutationFn: () =>
      generateAIInterviewReport(jobId!, applicationId!, newIdempotencyKey()),
    onSuccess: (result) => {
      updateReportCache(result)
      const version = result.versions.find(
        (item) => item.version_number === result.current_version_number,
      )
      if (version?.ai_failure_code) {
        void messageApi.warning('AI 暂不可用，已创建可编辑的人工草稿')
      } else {
        void messageApi.success('AI 面试报告草稿已生成')
      }
    },
    onError: (error) =>
      void messageApi.error(error instanceof Error ? error.message : '生成报告失败'),
  })
  const saveMutation = useMutation({
    mutationFn: () => {
      if (!currentVersion) throw new Error('缺少面试报告当前版本')
      if (!contentDirty) throw new Error('报告内容未发生变化')
      return createInterviewReportVersion(
        jobId!,
        applicationId!,
        newIdempotencyKey(),
        currentVersion.id,
        normalizedContent(draft),
      )
    },
    onSuccess: (result) => {
      updateReportCache(result)
      void messageApi.success(`面试报告 V${result.current_version_number} 已保存`)
    },
    onError: (error) =>
      void messageApi.error(error instanceof Error ? error.message : '保存报告失败'),
  })
  const confirmMutation = useMutation({
    mutationFn: async () => {
      if (!currentVersion || !report.data) throw new Error('缺少面试报告当前版本')
      const content = normalizedContent(draft)
      if (!content.conclusion) throw new Error('请选择报告结论')
      if (!content.executive_summary) throw new Error('请填写执行摘要')
      let target = report.data
      if (contentDirty) {
        target = await createInterviewReportVersion(
          jobId!,
          applicationId!,
          newIdempotencyKey(),
          currentVersion.id,
          content,
        )
      }
      const targetVersion = target.versions.find(
        (version) => version.version_number === target.current_version_number,
      )
      if (!targetVersion) throw new Error('无法确定待确认版本')
      return confirmInterviewReport(jobId!, applicationId!, targetVersion.id)
    },
    onSuccess: (result) => {
      updateReportCache(result)
      setConfirmOpen(false)
      void messageApi.success('面试报告已确认并锁定')
    },
    onError: (error) => {
      setConfirmOpen(false)
      void messageApi.error(error instanceof Error ? error.message : '确认报告失败')
    },
  })

  const versionItems = useMemo(
    () => [...(report.data?.versions ?? [])].sort((left, right) => right.version_number - left.version_number),
    [report.data?.versions],
  )
  const evidenceContext = selectedVersion?.evidence_snapshot ?? context.data

  return (
    <>
      {contextHolder}
      <div className="page-heading">
        <div>
          <Space size="small" wrap>
            <Title level={2}>
              {context.data?.candidate_name || context.data?.candidate_code || '面试报告'}
            </Title>
            {report.data?.status === 'draft' && <Tag color="processing">草稿</Tag>}
            {report.data?.status === 'confirmed' && <Tag color="success">已确认</Tag>}
          </Space>
          <Text type="secondary">
            {context.data?.candidate_code ?? '读取候选人中'} · {job.data?.title ?? '读取岗位中'}
          </Text>
        </div>
        <Space wrap>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate(`/jobs/${jobId}/interview-reports`)}
          >
            返回报告列表
          </Button>
          <Button
            icon={<ReloadOutlined />}
            loading={context.isFetching || report.isFetching}
            onClick={() => {
              void context.refetch()
              void report.refetch()
            }}
          >
            刷新
          </Button>
          {canManageRecruitment(auth.user) &&
            !archived &&
            !merged &&
            report.data?.status === 'confirmed' &&
            currentVersion?.conclusion === 'hire' && (
              <Button
                type="primary"
                icon={<DollarOutlined />}
                onClick={() =>
                  navigate(
                    `/offers?create=1&jobId=${encodeURIComponent(jobId!)}&applicationId=${encodeURIComponent(applicationId!)}`,
                  )
                }
              >
                创建 Offer
              </Button>
            )}
        </Space>
      </div>

      <InterviewModuleNav jobId={jobId} activeKey="reports" />

      {archived && <Alert className="page-alert" type="warning" showIcon message="该职位已归档，面试报告仅供查看" />}
      {merged && <Alert className="page-alert" type="warning" showIcon message="该应聘记录已合并，面试报告仅供查看" />}
      {roleReadOnly && !archived && !merged && <Alert className="page-alert" type="warning" showIcon message="当前角色可查看面试报告，但不能创建、修改或确认" />}
      {reportLocked && <Alert className="page-alert" type="success" showIcon message="报告已确认并锁定" description={`确认时间：${formatDateTime(report.data?.confirmed_at ?? null)}`} />}
      {pageError && (
        <Alert
          className="page-alert"
          type="error"
          showIcon
          message="无法读取面试报告"
          description={pageError instanceof ApiError ? pageError.message : '请稍后重试'}
        />
      )}
      {loading && <Skeleton active paragraph={{ rows: 12 }} />}

      {!loading && !pageError && context.data && report.data === null && (
        <>
          <section className="report-start-panel">
            <div>
              <FileTextOutlined className="report-start-icon" />
              <div>
                <Title level={3}>尚未创建面试报告</Title>
                <Text type="secondary">
                  当前有 {context.data.submitted_evaluations.length} 轮已提交评价，
                  {context.data.missing_rounds.length} 轮缺失
                </Text>
              </div>
            </div>
            {!readOnly && (
              <Space wrap>
                <Button
                  icon={<FileTextOutlined />}
                  loading={manualMutation.isPending}
                  disabled={aiMutation.isPending}
                  onClick={() => manualMutation.mutate()}
                >
                  人工起草
                </Button>
                <Button
                  type="primary"
                  icon={<RobotOutlined />}
                  loading={aiMutation.isPending}
                  disabled={manualMutation.isPending}
                  onClick={() => aiMutation.mutate()}
                >
                  AI 生成草稿
                </Button>
              </Space>
            )}
          </section>
          <EvidenceView context={context.data} />
        </>
      )}

      {!loading && !pageError && report.data && selectedVersion && evidenceContext && (
        <>
          {selectedVersion.ai_failure_code && (
            <Alert
              className="page-alert"
              type="warning"
              showIcon
              message="AI 生成失败，当前版本已转为人工草稿"
              description={selectedVersion.ai_failure_message || '可继续人工填写并保存新版本。'}
            />
          )}
          {viewingHistory && (
            <Alert className="page-alert" type="info" showIcon message={`正在查看历史版本 V${selectedVersion.version_number}`} />
          )}
          <div className="report-workbench">
            <main className="report-main-panel">
              <div className="report-version-heading">
                <div>
                  <Title level={3}>面试报告 V{selectedVersion.version_number}</Title>
                  <Text type="secondary">
                    {selectedVersion.generation_mode === 'ai' ? 'AI 草稿' : '人工版本'} · {selectedVersion.created_by_display_name} · {formatDateTime(selectedVersion.created_at)}
                  </Text>
                </div>
                {selectedVersion.conclusion && (
                  <Tag color={conclusionMeta[selectedVersion.conclusion].color}>
                    {conclusionMeta[selectedVersion.conclusion].label}
                  </Tag>
                )}
              </div>
              <Tabs
                items={[
                  {
                    key: 'content',
                    label: '报告内容',
                    children: (
                      <ReportContentEditor
                        value={viewingHistory ? contentFromVersion(selectedVersion) : draft}
                        disabled={readOnly}
                        onChange={setDraft}
                      />
                    ),
                  },
                  {
                    key: 'evidence',
                    label: `证据依据 (${selectedVersion.evaluation_ids.length})`,
                    children: <EvidenceView context={evidenceContext} />,
                  },
                ]}
              />
              {!readOnly && (
                <div className="sticky-actions report-actions">
                  <Space wrap>
                    <Button
                      icon={<SaveOutlined />}
                      disabled={!contentDirty}
                      loading={saveMutation.isPending}
                      onClick={() => saveMutation.mutate()}
                    >
                      保存新版本
                    </Button>
                    <Button
                      type="primary"
                      icon={<CheckOutlined />}
                      loading={confirmMutation.isPending}
                      onClick={() => {
                        const content = normalizedContent(draft)
                        if (!content.conclusion) {
                          void messageApi.error('请选择报告结论')
                          return
                        }
                        if (!content.executive_summary) {
                          void messageApi.error('请填写执行摘要')
                          return
                        }
                        setConfirmOpen(true)
                      }}
                    >
                      确认报告
                    </Button>
                  </Space>
                  {contentDirty && <Text type="warning">有未保存修改</Text>}
                </div>
              )}
            </main>

            <aside className="report-version-history" aria-label="报告版本历史">
              <div className="report-section-heading">
                <Title level={4}>版本历史</Title>
                <Tag>{versionItems.length}</Tag>
              </div>
              <div className="report-version-list">
                {versionItems.map((version) => (
                  <button
                    key={version.id}
                    type="button"
                    className={`report-version-item${version.id === selectedVersion.id ? ' is-selected' : ''}`}
                    onClick={() => {
                      setSelectedVersionId(version.id)
                      if (version.id === currentVersion?.id) setDraft(contentFromVersion(version))
                    }}
                  >
                    <span>
                      <strong>V{version.version_number}</strong>
                      <small>{version.generation_mode === 'ai' ? 'AI 草稿' : '人工版本'}</small>
                    </span>
                    <Text type="secondary">{formatDateTime(version.created_at)}</Text>
                  </button>
                ))}
              </div>
            </aside>
          </div>
        </>
      )}

      <Modal
        title="确认面试报告"
        open={confirmOpen}
        okText="确认并锁定"
        cancelText="继续编辑"
        confirmLoading={confirmMutation.isPending}
        onCancel={() => setConfirmOpen(false)}
        onOk={() => confirmMutation.mutate()}
      >
        <Paragraph>
          {contentDirty
            ? '系统会先保存当前修改为新版本，再确认并锁定该版本。'
            : `确认后 V${currentVersion?.version_number ?? ''} 将锁定，不能继续修改。`}
        </Paragraph>
      </Modal>
    </>
  )
}
