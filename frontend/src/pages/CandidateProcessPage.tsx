import {
  ArrowLeftOutlined,
  CalendarOutlined,
  ClockCircleOutlined,
  EyeOutlined,
  HistoryOutlined,
  ReloadOutlined,
  SwapOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Drawer,
  Empty,
  Input,
  InputNumber,
  Modal,
  Select,
  Skeleton,
  Space,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  ApiError,
  fetchCandidateProcesses,
  fetchCandidateProcessTimeline,
  fetchJob,
  fetchScreeningBatches,
  updateCandidateStage,
  type AIGroup,
  type CandidateProcessCardRecord,
  type CandidateProcessFilters,
  type CandidateStage,
} from '../api/client'

const { Title, Text, Paragraph } = Typography

const stageOrder: CandidateStage[] = [
  'unprocessed',
  'pending',
  'shortlisted',
  'to_contact',
  'contacted',
  'to_interview',
  'completed',
  'rejected',
]

const stageMeta: Record<
  CandidateStage,
  { label: string; color: string; description: string }
> = {
  unprocessed: { label: '待人工处理', color: 'default', description: 'AI 已完成，等待人工判断' },
  pending: { label: '待定', color: 'warning', description: '需要补充信息或进一步确认' },
  shortlisted: { label: '初筛通过', color: 'success', description: '招聘专员确认进入后续流程' },
  to_contact: { label: '待联系', color: 'blue', description: '等待联系候选人' },
  contacted: { label: '已联系', color: 'cyan', description: '已完成首次沟通' },
  to_interview: { label: '待面试', color: 'purple', description: '等待后续面试安排' },
  completed: { label: '已结束', color: 'success', description: '该职位内人工流程已经完成' },
  rejected: { label: '已淘汰', color: 'error', description: '人工确认不再继续推进' },
}

const aiGroupMeta: Record<AIGroup, { label: string; color: string }> = {
  passed: { label: '通过组', color: 'success' },
  low_match: { label: '低匹配组', color: 'warning' },
  auto_rejected: { label: '自动淘汰组', color: 'error' },
}

const allowedTransitions: Record<CandidateStage, CandidateStage[]> = {
  unprocessed: ['pending', 'shortlisted', 'rejected'],
  pending: ['shortlisted', 'rejected'],
  shortlisted: ['pending', 'to_contact', 'rejected'],
  to_contact: ['shortlisted', 'contacted', 'rejected'],
  contacted: ['to_contact', 'to_interview', 'rejected'],
  to_interview: ['contacted', 'completed', 'rejected'],
  completed: [],
  rejected: [],
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function stageDuration(value: string) {
  const hours = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 3_600_000))
  if (hours < 1) return '不足 1 小时'
  if (hours < 24) return `${hours} 小时`
  return `${Math.floor(hours / 24)} 天`
}

export function CandidateProcessPage() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [batchId, setBatchId] = useState<string>()
  const [stage, setStage] = useState<CandidateStage>()
  const [aiGroup, setAIGroup] = useState<AIGroup>()
  const [minScore, setMinScore] = useState<number>()
  const [maxScore, setMaxScore] = useState<number>()
  const [search, setSearch] = useState('')
  const [changeTarget, setChangeTarget] = useState<CandidateProcessCardRecord>()
  const [targetStage, setTargetStage] = useState<CandidateStage>()
  const [reason, setReason] = useState('')
  const [timelineTarget, setTimelineTarget] = useState<CandidateProcessCardRecord>()

  const filters = useMemo<CandidateProcessFilters>(
    () => ({ batchId, stage, aiGroup, minScore, maxScore, query: search }),
    [aiGroup, batchId, maxScore, minScore, search, stage],
  )
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
  })
  const batches = useQuery({
    queryKey: ['screening-batches', jobId],
    queryFn: () => fetchScreeningBatches(jobId!),
    enabled: Boolean(jobId),
  })
  const candidates = useQuery({
    queryKey: ['candidate-processes', jobId, filters],
    queryFn: () => fetchCandidateProcesses(jobId!, filters),
    enabled: Boolean(jobId),
  })
  const timeline = useQuery({
    queryKey: ['candidate-process-timeline', jobId, timelineTarget?.document_id],
    queryFn: () => fetchCandidateProcessTimeline(jobId!, timelineTarget!.document_id),
    enabled: Boolean(jobId && timelineTarget),
  })
  const changeMutation = useMutation({
    mutationFn: () =>
      updateCandidateStage(
        jobId!,
        changeTarget!.document_id,
        changeTarget!.current_stage,
        targetStage!,
        reason,
      ),
    onSuccess: async () => {
      messageApi.success('候选人阶段已更新')
      setChangeTarget(undefined)
      setTargetStage(undefined)
      setReason('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['candidate-processes', jobId] }),
        queryClient.invalidateQueries({ queryKey: ['screening-results', jobId] }),
        queryClient.invalidateQueries({ queryKey: ['candidate-process-timeline', jobId] }),
      ])
    },
  })

  const visibleStages = stage ? [stage] : stageOrder
  const grouped = useMemo(() => {
    const result: Record<CandidateStage, CandidateProcessCardRecord[]> = {
      unprocessed: [],
      pending: [],
      shortlisted: [],
      to_contact: [],
      contacted: [],
      to_interview: [],
      completed: [],
      rejected: [],
    }
    candidates.data?.forEach((candidate) => result[candidate.current_stage].push(candidate))
    return result
  }, [candidates.data])
  const pageError = job.error ?? candidates.error ?? batches.error
  const rank = (value: CandidateStage) => stageOrder.indexOf(value)
  const reasonRequired = Boolean(
    changeTarget &&
      targetStage &&
      (targetStage === 'rejected' || rank(targetStage) < rank(changeTarget.current_stage)),
  )

  function openStageChange(candidate: CandidateProcessCardRecord) {
    const nextStage = allowedTransitions[candidate.current_stage].find(
      (item) => item !== 'rejected' && rank(item) > rank(candidate.current_stage),
    )
    setChangeTarget(candidate)
    setTargetStage(nextStage ?? allowedTransitions[candidate.current_stage][0])
    setReason('')
  }

  function resetFilters() {
    setBatchId(undefined)
    setStage(undefined)
    setAIGroup(undefined)
    setMinScore(undefined)
    setMaxScore(undefined)
    setSearch('')
  }

  return (
    <>
      {contextHolder}
      <div className="page-heading">
        <div>
          <Title level={2}>{job.data?.title ?? '候选人流程看板'}</Title>
          <Text type="secondary">管理 AI 初筛完成后的人工联系与推进状态</Text>
        </div>
        <Space wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>
            返回职位
          </Button>
          <Button onClick={() => navigate(`/jobs/${jobId}/results`)}>筛选结果</Button>
          <Button
            icon={<ReloadOutlined />}
            loading={candidates.isFetching}
            onClick={() => void candidates.refetch()}
          >
            刷新
          </Button>
        </Space>
      </div>

      <Card className="candidate-board-filter-card" size="small">
        <Space wrap size="middle">
          <Input.Search
            allowClear
            value={search}
            placeholder="搜索候选人编号、文件名或技能"
            className="candidate-board-search"
            onChange={(event) => setSearch(event.target.value)}
          />
          <Select
            allowClear
            value={batchId}
            placeholder="全部批次"
            className="candidate-board-filter"
            options={batches.data?.map((batch) => ({ label: batch.name, value: batch.id }))}
            onChange={setBatchId}
          />
          <Select
            allowClear
            value={stage}
            placeholder="全部阶段"
            className="candidate-board-filter"
            options={stageOrder.map((item) => ({
              label: stageMeta[item].label,
              value: item,
            }))}
            onChange={setStage}
          />
          <Select
            allowClear
            value={aiGroup}
            placeholder="全部 AI 分组"
            className="candidate-board-filter"
            options={Object.entries(aiGroupMeta).map(([value, meta]) => ({
              label: meta.label,
              value,
            }))}
            onChange={setAIGroup}
          />
          <InputNumber
            min={0}
            max={100}
            value={minScore}
            placeholder="最低分"
            onChange={(value) => setMinScore(value ?? undefined)}
          />
          <InputNumber
            min={0}
            max={100}
            value={maxScore}
            placeholder="最高分"
            onChange={(value) => setMaxScore(value ?? undefined)}
          />
          <Button onClick={resetFilters}>重置</Button>
        </Space>
      </Card>

      {(job.isError || candidates.isError || batches.isError) && (
        <Alert
          type="error"
          showIcon
          className="page-alert"
          message="无法读取候选人流程看板"
          description={
            pageError instanceof ApiError
              ? pageError.message
              : '请稍后重试'
          }
        />
      )}
      {candidates.isPending && <Skeleton active paragraph={{ rows: 10 }} />}
      {candidates.isSuccess && !candidates.data.length && (
        <Empty description="当前条件下没有已完成 AI 初筛的候选人" />
      )}
      {candidates.isSuccess && candidates.data.length > 0 && (
        <div className="candidate-board" aria-label="候选人流程看板">
          {visibleStages.map((stageKey) => (
            <section className="candidate-board-column" key={stageKey}>
              <div className="candidate-board-column-heading">
                <div>
                  <Space size="small">
                    <Title level={5}>{stageMeta[stageKey].label}</Title>
                    <Tag>{grouped[stageKey].length}</Tag>
                  </Space>
                  <Text type="secondary">{stageMeta[stageKey].description}</Text>
                </div>
              </div>
              <div className="candidate-board-column-body">
                {grouped[stageKey].length === 0 && (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无候选人" />
                )}
                {grouped[stageKey].map((candidate) => (
                  <Card
                    key={candidate.document_id}
                    size="small"
                    className="candidate-flow-card"
                    title={candidate.candidate_code}
                    extra={<Tag color="blue">{candidate.total_score.toFixed(1)} 分</Tag>}
                  >
                    <Paragraph ellipsis={{ rows: 1 }} title={candidate.original_filename}>
                      {candidate.original_filename}
                    </Paragraph>
                    <Space wrap size={[4, 6]}>
                      <Tag color={aiGroupMeta[candidate.ai_group].color}>
                        {aiGroupMeta[candidate.ai_group].label}
                      </Tag>
                      <Tag>{candidate.batch_name || '未命名批次'}</Tag>
                    </Space>
                    <div className="candidate-flow-skills">
                      {candidate.skills.length ? (
                        candidate.skills.map((skill) => <Tag key={skill}>{skill}</Tag>)
                      ) : (
                        <Text type="secondary">暂无技能标签</Text>
                      )}
                    </div>
                    <Text type="secondary" className="candidate-flow-duration">
                      <ClockCircleOutlined /> 当前阶段 {stageDuration(candidate.stage_entered_at)}
                    </Text>
                    <div className="candidate-flow-actions">
                      <Button
                        size="small"
                        icon={<EyeOutlined />}
                        onClick={() =>
                          navigate(
                            `/jobs/${jobId}/batches/${candidate.batch_id}/documents/${candidate.document_id}/history`,
                          )
                        }
                      >
                        查看档案
                      </Button>
                      <Button
                        size="small"
                        icon={<CalendarOutlined />}
                        onClick={() =>
                          navigate(
                            `/jobs/${jobId}/candidates/${candidate.document_id}/interview-schedule`,
                          )
                        }
                      >
                        面试安排
                      </Button>
                      <Button
                        size="small"
                        icon={<HistoryOutlined />}
                        onClick={() => setTimelineTarget(candidate)}
                      >
                        时间线
                      </Button>
                      {allowedTransitions[candidate.current_stage].length > 0 && (
                        <Button
                          size="small"
                          type="primary"
                          icon={<SwapOutlined />}
                          onClick={() => openStageChange(candidate)}
                        >
                          调整阶段
                        </Button>
                      )}
                    </div>
                  </Card>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      <Modal
        title={changeTarget ? `调整 ${changeTarget.candidate_code} 的阶段` : '调整候选人阶段'}
        open={Boolean(changeTarget)}
        okText="确认调整"
        cancelText="取消"
        confirmLoading={changeMutation.isPending}
        okButtonProps={{ disabled: !targetStage || (reasonRequired && !reason.trim()) }}
        onCancel={() => {
          setChangeTarget(undefined)
          setTargetStage(undefined)
          setReason('')
        }}
        onOk={() => changeMutation.mutate()}
      >
        {changeMutation.isError && (
          <Alert
            type="error"
            showIcon
            className="page-alert"
            message="阶段调整失败"
            description={changeMutation.error.message}
          />
        )}
        <Space direction="vertical" size="middle" className="candidate-stage-form">
          <div>
            <Text type="secondary">当前阶段</Text>
            <div>
              {changeTarget && (
                <Tag color={stageMeta[changeTarget.current_stage].color}>
                  {stageMeta[changeTarget.current_stage].label}
                </Tag>
              )}
            </div>
          </div>
          <div>
            <Text type="secondary">目标阶段</Text>
            <Select
              value={targetStage}
              className="candidate-stage-select"
              options={(changeTarget ? allowedTransitions[changeTarget.current_stage] : []).map(
                (item) => ({ label: stageMeta[item].label, value: item }),
              )}
              onChange={setTargetStage}
            />
          </div>
          <div>
            <Text type="secondary">调整原因{reasonRequired ? '（必填）' : '（选填）'}</Text>
            <Input.TextArea
              value={reason}
              rows={4}
              maxLength={2000}
              showCount
              placeholder="淘汰或退回时请说明原因"
              onChange={(event) => setReason(event.target.value)}
            />
          </div>
        </Space>
      </Modal>

      <Drawer
        title={timelineTarget ? `${timelineTarget.candidate_code} · 操作时间线` : '操作时间线'}
        open={Boolean(timelineTarget)}
        width={520}
        onClose={() => setTimelineTarget(undefined)}
      >
        {timeline.isPending && <Skeleton active paragraph={{ rows: 6 }} />}
        {timeline.isError && (
          <Alert type="error" showIcon message="无法读取操作时间线" />
        )}
        {timeline.isSuccess && timeline.data.length === 0 && (
          <Empty description="尚无人工操作记录" />
        )}
        {timeline.isSuccess && timeline.data.length > 0 && (
          <Timeline
            items={timeline.data.map((event) => ({
              color: stageMeta[event.to_stage].color,
              children: (
                <div>
                  <Text strong>
                    {stageMeta[event.from_stage].label} → {stageMeta[event.to_stage].label}
                  </Text>
                  <div>
                    <Text type="secondary">
                      {event.operator_display_name} · {formatDate(event.created_at)}
                    </Text>
                  </div>
                  {event.reason && <Paragraph>{event.reason}</Paragraph>}
                </div>
              ),
            }))}
          />
        )}
      </Drawer>
    </>
  )
}
