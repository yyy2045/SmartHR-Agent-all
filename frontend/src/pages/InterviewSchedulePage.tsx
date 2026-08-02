import {
  ArrowLeftOutlined,
  CalendarOutlined,
  CloseCircleOutlined,
  CopyOutlined,
  EnvironmentOutlined,
  FileDoneOutlined,
  LinkOutlined,
  ReloadOutlined,
  SendOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Select,
  Skeleton,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  ApiError,
  cancelCandidateInterviewRound,
  createCandidateInterviewSchedule,
  fetchCandidateInterviewSchedule,
  fetchCandidateProcesses,
  fetchMessageTemplate,
  fetchMessageTemplates,
  fetchInterviewPlanVersions,
  fetchJob,
  previewCommunication,
  recordCommunicationCopyAudit,
  rescheduleCandidateInterviewRound,
  type CommunicationPreviewRecord,
  type InterviewMethod,
  type InterviewRound,
  type InterviewScheduleRoundRecord,
  type MessageTemplateSummaryRecord,
} from '../api/client'
import { useAuth } from '../auth/context'
import { canManageRecruitment } from '../auth/permissions'

const { Title, Text, Paragraph } = Typography

const interviewCommunicationText = {
  title: '\u751f\u6210\u9762\u8bd5\u901a\u77e5\u6587\u6848',
  safetyMessage:
    '\u7cfb\u7edf\u53ea\u751f\u6210\u53ef\u590d\u5236\u6587\u6848\uff0c\u4e0d\u8fde\u63a5\u817e\u8baf\u4f1a\u8bae\u6216\u5916\u90e8\u53d1\u9001\u6e20\u9053',
  safetyDescription:
    '\u817e\u8baf\u4f1a\u8bae\u94fe\u63a5\u3001\u4f1a\u8bae\u53f7\u6216\u7ebf\u4e0b\u9762\u8bd5\u5730\u5740\u6765\u81ea\u5f53\u524d\u9762\u8bd5\u5b89\u6392\uff1b\u590d\u5236\u540e\u7531\u62db\u8058\u4e13\u5458\u901a\u8fc7\u5916\u90e8\u5de5\u5177\u53d1\u9001\u3002',
  templateLoadError: '\u65e0\u6cd5\u8bfb\u53d6\u6c9f\u901a\u6a21\u677f',
  templateDetailLoadError: '\u65e0\u6cd5\u8bfb\u53d6\u6a21\u677f\u8be6\u60c5',
  previewError: '\u751f\u6210\u9762\u8bd5\u901a\u77e5\u6587\u6848\u5931\u8d25',
  copyUnsupported: '\u5f53\u524d\u6d4f\u89c8\u5668\u4e0d\u652f\u6301\u526a\u8d34\u677f',
  copySuccess: '\u9762\u8bd5\u901a\u77e5\u6587\u6848\u5df2\u590d\u5236\u5e76\u8bb0\u5f55\u7559\u75d5',
  copyError: '\u590d\u5236\u5e76\u7559\u75d5\u5931\u8d25',
  retryLater: '\u8bf7\u7a0d\u540e\u91cd\u8bd5',
  selectTemplate: '\u9009\u62e9\u9762\u8bd5\u901a\u77e5\u6a21\u677f',
  generatePreview: '\u751f\u6210\u9884\u89c8',
  subjectLabel: '\u9762\u8bd5\u901a\u77e5\u6807\u9898',
  bodyLabel: '\u9762\u8bd5\u901a\u77e5\u6b63\u6587',
  copyAndAudit: '\u590d\u5236\u6587\u6848\u5e76\u7559\u75d5',
  templateVersion: '\u6a21\u677f',
}

interface RoundDraft {
  planRoundId: string
  scheduledStartAt: string
  interviewMethod: InterviewMethod
  location: string
  meetingUrl: string
}

const methodMeta: Record<InterviewMethod, { label: string; color: string }> = {
  onsite: { label: '线下面试', color: 'blue' },
  online: { label: '在线面试', color: 'cyan' },
  phone: { label: '电话面试', color: 'purple' },
}

const scheduleStatusMeta = {
  scheduled: { label: '已安排', color: 'processing' },
  partially_cancelled: { label: '部分取消', color: 'warning' },
  cancelled: { label: '已取消', color: 'default' },
} as const

const roundStatusMeta = {
  scheduled: { label: '已安排', color: 'processing' },
  rescheduled: { label: '已改期', color: 'warning' },
  cancelled: { label: '已取消', color: 'default' },
} as const

function toLocalInput(value: Date | string): string {
  const date = typeof value === 'string' ? new Date(value) : value
  const adjusted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return adjusted.toISOString().slice(0, 16)
}

function defaultRoundTime(index: number): string {
  const date = new Date()
  date.setDate(date.getDate() + index + 1)
  date.setHours(10, 0, 0, 0)
  return toLocalInput(date)
}

function createDrafts(rounds: InterviewRound[]): RoundDraft[] {
  return rounds.map((round, index) => ({
    planRoundId: round.id,
    scheduledStartAt: defaultRoundTime(index),
    interviewMethod: round.round_type === 'phone' ? 'phone' : 'onsite',
    location: round.round_type === 'phone' ? '' : '公司会议室',
    meetingUrl: '',
  }))
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    weekday: 'short',
  }).format(new Date(value))
}

function validateArrangement(draft: RoundDraft): string | undefined {
  if (!draft.scheduledStartAt || Number.isNaN(new Date(draft.scheduledStartAt).getTime())) {
    return '请填写有效的面试时间'
  }
  if (draft.interviewMethod === 'onsite' && !draft.location.trim()) {
    return '线下面试必须填写地点'
  }
  if (draft.interviewMethod === 'online') {
    if (!draft.meetingUrl.trim()) return '在线面试必须填写会议链接'
    try {
      const url = new URL(draft.meetingUrl.trim())
      if (!['http:', 'https:'].includes(url.protocol)) return '会议链接格式不正确'
    } catch {
      return '会议链接格式不正确'
    }
  }
  return undefined
}

export function InterviewSchedulePage() {
  const { jobId, applicationId } = useParams()
  const auth = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [selectedPlanId, setSelectedPlanId] = useState<string>()
  const [drafts, setDrafts] = useState<RoundDraft[]>([])
  const [editingRound, setEditingRound] = useState<InterviewScheduleRoundRecord>()
  const [editDraft, setEditDraft] = useState<RoundDraft>()
  const [editReason, setEditReason] = useState('')
  const [cancellingRound, setCancellingRound] = useState<InterviewScheduleRoundRecord>()
  const [cancelReason, setCancelReason] = useState('')
  const [communicationOpen, setCommunicationOpen] = useState(false)
  const [communicationRound, setCommunicationRound] = useState<InterviewScheduleRoundRecord>()
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>()
  const [communicationDraft, setCommunicationDraft] = useState<CommunicationPreviewRecord>()
  const [communicationCopyKey, setCommunicationCopyKey] = useState(() => crypto.randomUUID())

  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
  })
  const candidates = useQuery({
    queryKey: ['candidate-processes', jobId],
    queryFn: () => fetchCandidateProcesses(jobId!),
    enabled: Boolean(jobId),
  })
  const plans = useQuery({
    queryKey: ['interview-plan-versions', jobId],
    queryFn: () => fetchInterviewPlanVersions(jobId!),
    enabled: Boolean(jobId),
  })
  const schedule = useQuery({
    queryKey: ['candidate-interview-schedule', jobId, applicationId],
    queryFn: () => fetchCandidateInterviewSchedule(jobId!, applicationId!),
    enabled: Boolean(jobId && applicationId),
  })

  const interviewMessageTemplates = useQuery({
    queryKey: ['message-templates', { templateType: 'interview_invitation' }],
    queryFn: () =>
      fetchMessageTemplates({
        status: 'active',
        templateType: 'interview_invitation',
        limit: 20,
        offset: 0,
      }),
    enabled: communicationOpen,
  })
  const selectedTemplate = useQuery({
    queryKey: ['message-template', selectedTemplateId],
    queryFn: () => fetchMessageTemplate(selectedTemplateId!),
    enabled: communicationOpen && Boolean(selectedTemplateId),
  })

  const candidate = candidates.data?.find((item) => item.application_id === applicationId)
  const confirmedPlans = useMemo(
    () => plans.data?.filter((item) => item.status === 'confirmed') ?? [],
    [plans.data],
  )
  const selectedPlan = confirmedPlans.find((item) => item.id === selectedPlanId)
  const archived = job.data?.status === 'archived'
  const canWrite = canManageRecruitment(auth.user) && job.data?.status === 'active'
  const pageError = job.error ?? candidates.error ?? plans.error ?? schedule.error

  useEffect(() => {
    if (!selectedPlanId && confirmedPlans.length) {
      setSelectedPlanId(confirmedPlans[0].id)
    }
  }, [confirmedPlans, selectedPlanId])

  useEffect(() => {
    if (selectedPlan && !schedule.data) setDrafts(createDrafts(selectedPlan.rounds))
  }, [schedule.data, selectedPlan])

  useEffect(() => {
    if (!communicationOpen || selectedTemplateId) return
    const firstTemplate = interviewMessageTemplates.data?.items[0]
    if (firstTemplate) setSelectedTemplateId(firstTemplate.id)
  }, [communicationOpen, interviewMessageTemplates.data?.items, selectedTemplateId])

  const createMutation = useMutation({
    mutationFn: () => {
      if (!jobId || !applicationId || !selectedPlan) throw new Error('缺少面试方案')
      const firstError = drafts.map(validateArrangement).find(Boolean)
      if (firstError) throw new Error(firstError)
      return createCandidateInterviewSchedule(jobId, applicationId, {
        plan_version_id: selectedPlan.id,
        rounds: drafts.map((draft) => ({
          plan_round_id: draft.planRoundId,
          scheduled_start_at: new Date(draft.scheduledStartAt).toISOString(),
          interview_method: draft.interviewMethod,
          location: draft.interviewMethod === 'onsite' ? draft.location.trim() : null,
          meeting_url: draft.interviewMethod === 'online' ? draft.meetingUrl.trim() : null,
        })),
      })
    },
    onSuccess: (result) => {
      queryClient.setQueryData(
        ['candidate-interview-schedule', jobId, applicationId],
        result,
      )
      void messageApi.success('候选人面试安排已创建')
    },
    onError: (error) => {
      void messageApi.error(error instanceof Error ? error.message : '创建面试安排失败')
    },
  })

  const rescheduleMutation = useMutation({
    mutationFn: () => {
      if (!jobId || !applicationId || !editingRound || !editDraft) {
        throw new Error('缺少改期信息')
      }
      const arrangementError = validateArrangement(editDraft)
      if (arrangementError) throw new Error(arrangementError)
      if (!editReason.trim()) throw new Error('请填写改期原因')
      return rescheduleCandidateInterviewRound(jobId, applicationId, editingRound.id, {
        scheduled_start_at: new Date(editDraft.scheduledStartAt).toISOString(),
        interview_method: editDraft.interviewMethod,
        location: editDraft.interviewMethod === 'onsite' ? editDraft.location.trim() : null,
        meeting_url:
          editDraft.interviewMethod === 'online' ? editDraft.meetingUrl.trim() : null,
        reason: editReason.trim(),
      })
    },
    onSuccess: (result) => {
      queryClient.setQueryData(
        ['candidate-interview-schedule', jobId, applicationId],
        result,
      )
      setEditingRound(undefined)
      setEditDraft(undefined)
      setEditReason('')
      void messageApi.success('面试轮次已改期')
    },
    onError: (error) => {
      void messageApi.error(error instanceof Error ? error.message : '面试改期失败')
    },
  })

  const cancelMutation = useMutation({
    mutationFn: () => {
      if (!jobId || !applicationId || !cancellingRound) throw new Error('缺少取消信息')
      if (!cancelReason.trim()) throw new Error('请填写取消原因')
      return cancelCandidateInterviewRound(
        jobId,
        applicationId,
        cancellingRound.id,
        cancelReason.trim(),
      )
    },
    onSuccess: (result) => {
      queryClient.setQueryData(
        ['candidate-interview-schedule', jobId, applicationId],
        result,
      )
      setCancellingRound(undefined)
      setCancelReason('')
      void messageApi.success('面试轮次已取消')
    },
    onError: (error) => {
      void messageApi.error(error instanceof Error ? error.message : '取消面试失败')
    },
  })

  const communicationPreviewMutation = useMutation({
    mutationFn: ({ templateVersionId, roundId }: { templateVersionId: string; roundId: string }) =>
      previewCommunication({
        templateVersionId,
        contextType: 'interview_round',
        contextId: roundId,
      }),
    onSuccess: (draft) => setCommunicationDraft(draft),
    onError: (error) =>
      void messageApi.error(error instanceof Error ? error.message : interviewCommunicationText.previewError),
  })
  const communicationCopyMutation = useMutation({
    mutationFn: async (draft: CommunicationPreviewRecord) => {
      if (!navigator.clipboard) throw new Error(interviewCommunicationText.copyUnsupported)
      await navigator.clipboard.writeText(`${draft.subject}

${draft.body}`)
      return recordCommunicationCopyAudit({
        contextType: 'interview_round',
        contextId: draft.context_id,
        templateVersionId: draft.template_version_id,
        subject: draft.subject,
        body: draft.body,
        idempotencyKey: communicationCopyKey,
      })
    },
    onSuccess: () => {
      setCommunicationCopyKey(crypto.randomUUID())
      void messageApi.success(interviewCommunicationText.copySuccess)
    },
    onError: (error) =>
      void messageApi.error(error instanceof Error ? error.message : interviewCommunicationText.copyError),
  })

  function updateDraft(index: number, changes: Partial<RoundDraft>) {
    setDrafts((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? { ...item, ...changes } : item)),
    )
  }

  function openInterviewCommunication(round: InterviewScheduleRoundRecord) {
    setCommunicationRound(round)
    setCommunicationDraft(undefined)
    setCommunicationCopyKey(crypto.randomUUID())
    setCommunicationOpen(true)
  }

  function generateInterviewCommunication() {
    if (!communicationRound || !selectedTemplate.data?.current_version.id) return
    communicationPreviewMutation.mutate({
      templateVersionId: selectedTemplate.data.current_version.id,
      roundId: communicationRound.id,
    })
  }

  function openReschedule(round: InterviewScheduleRoundRecord) {
    setEditingRound(round)
    setEditDraft({
      planRoundId: round.plan_round_id,
      scheduledStartAt: toLocalInput(round.scheduled_start_at),
      interviewMethod: round.interview_method,
      location: round.location ?? '',
      meetingUrl: round.meeting_url ?? '',
    })
    setEditReason('')
  }

  const loading = job.isPending || candidates.isPending || plans.isPending || schedule.isPending

  const messageTemplateOptions = (interviewMessageTemplates.data?.items ?? []).map(
    (template: MessageTemplateSummaryRecord) => ({
      value: template.id,
      label: `${template.name} \u00b7 V${template.current_version_number}`,
    }),
  )

  return (
    <>
      {contextHolder}
      <div className="page-heading">
        <div>
          <Title level={2}>{schedule.data?.candidate_code ?? candidate?.candidate_code ?? '面试安排'}</Title>
          <Text type="secondary">
            {job.data?.title ? `${job.data.title} · ` : ''}按已确认方案安排候选人面试轮次
          </Text>
        </div>
        <Space wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/jobs/${jobId}/pipeline`)}>
            返回流程看板
          </Button>
          <Button
            icon={<ReloadOutlined />}
            loading={schedule.isFetching}
            onClick={() => void schedule.refetch()}
          >
            刷新
          </Button>
        </Space>
      </div>

      {!canWrite && job.data && (
        <Alert
          type="warning"
          showIcon
          className="page-alert"
          message={archived ? '该职位已归档，候选人面试安排仅供查看' : '当前角色可查看面试安排，但不能创建、改期或取消'}
        />
      )}
      {pageError && (
        <Alert
          type="error"
          showIcon
          className="page-alert"
          message="无法读取候选人面试安排"
          description={pageError instanceof ApiError ? pageError.message : '请稍后重试'}
        />
      )}
      {loading && <Skeleton active paragraph={{ rows: 8 }} />}

      {!loading && !pageError && !schedule.data && !canWrite && (
        <Card className="panel-card interview-schedule-create-card">
          <Empty description="该候选人尚未创建面试安排" />
        </Card>
      )}

      {!loading && !pageError && !schedule.data && canWrite && (
        <Card className="panel-card interview-schedule-create-card">
          <div className="section-heading">
            <div>
              <Title level={3}>创建候选人面试安排</Title>
              <Text type="secondary">创建后永久绑定所选方案版本，后续方案升级不影响本安排</Text>
            </div>
            <Select
              aria-label="选择已确认面试方案"
              value={selectedPlanId}
              className="interview-schedule-plan-select"
              placeholder="选择已确认方案"
              options={confirmedPlans.map((plan) => ({
                label: `面试方案 V${plan.version_number} · ${plan.rounds.length} 轮`,
                value: plan.id,
              }))}
              onChange={setSelectedPlanId}
            />
          </div>

          {!confirmedPlans.length && (
            <Empty description="当前职位还没有已确认的面试方案">
              {canWrite && (
                <Button type="primary" onClick={() => navigate(`/jobs/${jobId}/interview-plan`)}>
                  前往配置面试方案
                </Button>
              )}
            </Empty>
          )}

          {selectedPlan && (
            <div className="interview-schedule-round-list">
              {selectedPlan.rounds.map((round, index) => {
                const draft = drafts[index]
                if (!draft) return null
                return (
                  <Card
                    key={round.id}
                    size="small"
                    className="interview-schedule-round-card"
                    title={`${index + 1}. ${round.name}`}
                    extra={<Tag>{round.duration_minutes} 分钟</Tag>}
                  >
                    <Paragraph type="secondary">{round.focus || '未填写考察重点'}</Paragraph>
                    <div className="interview-schedule-form-grid">
                      <label>
                        <Text strong>计划时间</Text>
                        <Input
                          aria-label={`${round.name}计划时间`}
                          type="datetime-local"
                          value={draft.scheduledStartAt}
                          onChange={(event) =>
                            updateDraft(index, { scheduledStartAt: event.target.value })
                          }
                        />
                      </label>
                      <label>
                        <Text strong>面试方式</Text>
                        <Select
                          aria-label={`${round.name}面试方式`}
                          value={draft.interviewMethod}
                          options={Object.entries(methodMeta).map(([value, meta]) => ({
                            value,
                            label: meta.label,
                          }))}
                          onChange={(value) => updateDraft(index, { interviewMethod: value })}
                        />
                      </label>
                      {draft.interviewMethod === 'onsite' && (
                        <label>
                          <Text strong>面试地点</Text>
                          <Input
                            aria-label={`${round.name}面试地点`}
                            value={draft.location}
                            onChange={(event) => updateDraft(index, { location: event.target.value })}
                          />
                        </label>
                      )}
                      {draft.interviewMethod === 'online' && (
                        <label>
                          <Text strong>会议链接</Text>
                          <Input
                            aria-label={`${round.name}会议链接`}
                            value={draft.meetingUrl}
                            placeholder="https://"
                            onChange={(event) =>
                              updateDraft(index, { meetingUrl: event.target.value })
                            }
                          />
                        </label>
                      )}
                    </div>
                  </Card>
                )
              })}
              {canWrite && (
                <div className="sticky-actions">
                  <Button
                    type="primary"
                    size="large"
                    icon={<CalendarOutlined />}
                    loading={createMutation.isPending}
                    onClick={() => createMutation.mutate()}
                  >
                    创建面试安排
                  </Button>
                </div>
              )}
            </div>
          )}
        </Card>
      )}

      {!loading && schedule.data && (
        <div className="interview-schedule-view">
          <Card className="panel-card">
            <Space wrap size="middle">
              <Tag color={scheduleStatusMeta[schedule.data.status].color}>
                {scheduleStatusMeta[schedule.data.status].label}
              </Tag>
              <Text strong>面试方案 V{schedule.data.plan_version_number}</Text>
              <Text type="secondary">共 {schedule.data.rounds.length} 轮</Text>
              <Text type="secondary">创建于 {formatDateTime(schedule.data.created_at)}</Text>
            </Space>
          </Card>
          <div className="interview-schedule-round-list">
            {schedule.data.rounds.map((round, index) => (
              <Card
                key={round.id}
                className={`interview-schedule-round-card ${round.status === 'cancelled' ? 'is-cancelled' : ''}`}
                title={`${index + 1}. ${round.name}`}
                extra={<Tag color={roundStatusMeta[round.status].color}>{roundStatusMeta[round.status].label}</Tag>}
              >
                <div className="interview-schedule-summary-grid">
                  <div>
                    <Text type="secondary">计划时间</Text>
                    <Paragraph strong>{formatDateTime(round.scheduled_start_at)}</Paragraph>
                  </div>
                  <div>
                    <Text type="secondary">方式</Text>
                    <Paragraph>
                      <Tag color={methodMeta[round.interview_method].color}>
                        {methodMeta[round.interview_method].label}
                      </Tag>
                    </Paragraph>
                  </div>
                  <div>
                    <Text type="secondary">时长</Text>
                    <Paragraph>{round.duration_minutes} 分钟</Paragraph>
                  </div>
                  <div>
                    <Text type="secondary">地点或链接</Text>
                    {round.location && (
                      <Paragraph><EnvironmentOutlined /> {round.location}</Paragraph>
                    )}
                    {round.meeting_url && (
                      <Paragraph>
                        <a href={round.meeting_url} target="_blank" rel="noreferrer">
                          <LinkOutlined /> 打开会议链接
                        </a>
                      </Paragraph>
                    )}
                    {!round.location && !round.meeting_url && <Paragraph>无需配置</Paragraph>}
                  </div>
                </div>
                {round.last_change_reason && (
                  <Alert
                    type={round.status === 'cancelled' ? 'warning' : 'info'}
                    showIcon
                    message={round.status === 'cancelled' ? '取消原因' : '最近改期原因'}
                    description={round.last_change_reason}
                  />
                )}
                <Space wrap className="interview-schedule-actions">
                  <Button
                    type="primary"
                    ghost
                    icon={<FileDoneOutlined />}
                    onClick={() =>
                      navigate(
                        `/jobs/${jobId}/applications/${applicationId}/interview-evaluations/${round.id}`,
                      )
                    }
                  >
                    {!canWrite || round.status === 'cancelled' ? '查看评价' : '面试评价'}
                  </Button>
                  {canWrite && round.status !== 'cancelled' && (
                    <>
                      <Button icon={<SendOutlined />} onClick={() => openInterviewCommunication(round)}>
                        {interviewCommunicationText.title}
                      </Button>
                      <Button icon={<CalendarOutlined />} onClick={() => openReschedule(round)}>
                        改期
                      </Button>
                      <Button
                        danger
                        icon={<CloseCircleOutlined />}
                        onClick={() => {
                          setCancellingRound(round)
                          setCancelReason('')
                        }}
                      >
                        取消本轮
                      </Button>
                    </>
                  )}
                </Space>
              </Card>
            ))}
          </div>
        </div>
      )}

      {canWrite && <Modal
        title={interviewCommunicationText.title}
        open={communicationOpen}
        width={720}
        footer={null}
        onCancel={() => setCommunicationOpen(false)}
      >
        <Space direction="vertical" size="middle" className="interview-communication-panel">
          <Alert
            type="info"
            showIcon
            message={interviewCommunicationText.safetyMessage}
            description={interviewCommunicationText.safetyDescription}
          />
          {communicationRound && (
            <Text type="secondary">
              {communicationRound.name} ? {formatDateTime(communicationRound.scheduled_start_at)}
            </Text>
          )}
          {interviewMessageTemplates.error && (
            <Alert
              type="error"
              showIcon
              message={interviewCommunicationText.templateLoadError}
              description={interviewMessageTemplates.error instanceof Error ? interviewMessageTemplates.error.message : interviewCommunicationText.retryLater}
            />
          )}
          <div className="interview-communication-controls">
            <Select
              aria-label={interviewCommunicationText.selectTemplate}
              placeholder={interviewCommunicationText.selectTemplate}
              value={selectedTemplateId}
              loading={interviewMessageTemplates.isFetching}
              options={messageTemplateOptions}
              onChange={(value) => {
                setSelectedTemplateId(value)
                setCommunicationDraft(undefined)
              }}
            />
            <Button
              type="primary"
              loading={communicationPreviewMutation.isPending || selectedTemplate.isFetching}
              disabled={!communicationRound || !selectedTemplate.data?.current_version.id}
              onClick={generateInterviewCommunication}
            >
              {interviewCommunicationText.generatePreview}
            </Button>
          </div>
          {selectedTemplate.error && (
            <Alert
              type="error"
              showIcon
              message={interviewCommunicationText.templateDetailLoadError}
              description={selectedTemplate.error instanceof Error ? selectedTemplate.error.message : interviewCommunicationText.retryLater}
            />
          )}
          {communicationDraft && (
            <div className="interview-communication-preview">
              <Input value={communicationDraft.subject} readOnly aria-label={interviewCommunicationText.subjectLabel} />
              <Input.TextArea
                value={communicationDraft.body}
                readOnly
                rows={8}
                aria-label={interviewCommunicationText.bodyLabel}
              />
              <Space wrap>
                <Button
                  type="primary"
                  icon={<CopyOutlined />}
                  loading={communicationCopyMutation.isPending}
                  onClick={() => communicationCopyMutation.mutate(communicationDraft)}
                >
                  {interviewCommunicationText.copyAndAudit}
                </Button>
                <Text type="secondary">
                  {interviewCommunicationText.templateVersion} V{selectedTemplate.data?.current_version.version_number ?? '-'}
                </Text>
              </Space>
            </div>
          )}
        </Space>
      </Modal>}

      {canWrite && <Modal
        title={editingRound ? `改期：${editingRound.name}` : '面试改期'}
        open={Boolean(editingRound && editDraft)}
        okText="确认改期"
        cancelText="取消"
        confirmLoading={rescheduleMutation.isPending}
        onOk={() => rescheduleMutation.mutate()}
        onCancel={() => {
          setEditingRound(undefined)
          setEditDraft(undefined)
          setEditReason('')
        }}
      >
        {editDraft && (
          <Space direction="vertical" size="middle" className="interview-schedule-modal-form">
            <label>
              <Text strong>新的计划时间</Text>
              <Input
                aria-label="新的计划时间"
                type="datetime-local"
                value={editDraft.scheduledStartAt}
                onChange={(event) =>
                  setEditDraft({ ...editDraft, scheduledStartAt: event.target.value })
                }
              />
            </label>
            <label>
              <Text strong>面试方式</Text>
              <Select
                aria-label="改期后的面试方式"
                value={editDraft.interviewMethod}
                options={Object.entries(methodMeta).map(([value, meta]) => ({ value, label: meta.label }))}
                onChange={(value) => setEditDraft({ ...editDraft, interviewMethod: value })}
              />
            </label>
            {editDraft.interviewMethod === 'onsite' && (
              <label>
                <Text strong>面试地点</Text>
                <Input
                  aria-label="改期后的面试地点"
                  value={editDraft.location}
                  onChange={(event) => setEditDraft({ ...editDraft, location: event.target.value })}
                />
              </label>
            )}
            {editDraft.interviewMethod === 'online' && (
              <label>
                <Text strong>会议链接</Text>
                <Input
                  aria-label="改期后的会议链接"
                  value={editDraft.meetingUrl}
                  onChange={(event) => setEditDraft({ ...editDraft, meetingUrl: event.target.value })}
                />
              </label>
            )}
            <label>
              <Text strong>改期原因</Text>
              <Input.TextArea
                aria-label="改期原因"
                value={editReason}
                rows={3}
                maxLength={2_000}
                onChange={(event) => setEditReason(event.target.value)}
              />
            </label>
          </Space>
        )}
      </Modal>}

      {canWrite && <Modal
        title={cancellingRound ? `取消：${cancellingRound.name}` : '取消面试轮次'}
        open={Boolean(cancellingRound)}
        okText="确认取消本轮"
        okButtonProps={{ danger: true }}
        cancelText="返回"
        confirmLoading={cancelMutation.isPending}
        onOk={() => cancelMutation.mutate()}
        onCancel={() => {
          setCancellingRound(undefined)
          setCancelReason('')
        }}
      >
        <Paragraph type="secondary">取消后本轮不能再改期，请填写可追溯的取消原因。</Paragraph>
        <Input.TextArea
          aria-label="取消原因"
          value={cancelReason}
          rows={4}
          maxLength={2_000}
          onChange={(event) => setCancelReason(event.target.value)}
        />
      </Modal>}
    </>
  )
}
