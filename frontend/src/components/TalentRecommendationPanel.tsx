import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  EyeOutlined,
  PlusOutlined,
  ReloadOutlined,
  StopOutlined,
  SyncOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Checkbox,
  Collapse,
  Descriptions,
  Drawer,
  Empty,
  Input,
  List,
  Modal,
  Segmented,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  ApiError,
  cancelTalentRecommendation,
  createTalentRecommendation,
  fetchJob,
  fetchJobs,
  fetchTalentPoolGroups,
  fetchTalentRecommendation,
  fetchTalentRecommendations,
  retryTalentRecommendationFailures,
  selectTalentRecommendationCandidates,
  type TalentRecommendationResultRecord,
  type TalentRecommendationRunRecord,
  type TalentRecommendationRunStatus,
  type TalentRecommendationSelectionRecord,
} from '../api/client'
import { useAuth } from '../auth/context'

const { Text, Title, Paragraph } = Typography
const PAGE_SIZE = 20
const POLL_INTERVAL_MS = 2_000

const runStatusMeta: Record<
  TalentRecommendationRunStatus,
  { label: string; color: string }
> = {
  queued: { label: '等待处理', color: 'default' },
  retrieving: { label: '向量召回中', color: 'processing' },
  rescoring: { label: 'AI 重评中', color: 'processing' },
  completed: { label: '已完成', color: 'success' },
  partial: { label: '部分完成', color: 'warning' },
  failed: { label: '失败', color: 'error' },
  cancelled: { label: '已取消', color: 'default' },
}

const aiGroupMeta = {
  passed: { label: '通过', color: 'success' },
  low_match: { label: '低匹配', color: 'warning' },
  auto_rejected: { label: '自动淘汰', color: 'error' },
} as const

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback
}

function isRunning(status: TalentRecommendationRunStatus | undefined) {
  return status === 'queued' || status === 'retrieving' || status === 'rescoring'
}

function formatDateTime(value: string | null) {
  if (!value) return '未发生'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function objectText(value: Record<string, unknown>, key: string) {
  const item = value[key]
  return typeof item === 'string' || typeof item === 'number' ? String(item) : ''
}

function resultStatusLabel(result: TalentRecommendationResultRecord) {
  if (result.status === 'completed') return 'AI 重评完成'
  if (result.status === 'failed') return '重评失败'
  if (result.status === 'excluded') return '已排除'
  if (result.status === 'rescoring') return 'AI 重评中'
  return '仅向量召回'
}

function selectionStatusLabel(status: 'created' | 'existing' | 'failed') {
  if (status === 'created') return '已创建'
  if (status === 'existing') return '已存在'
  return '失败'
}

function ResultEvidence({ result }: { result: TalentRecommendationResultRecord }) {
  return (
    <div className="talent-recommendation-evidence">
      <section>
        <Text strong>向量命中证据</Text>
        {result.matched_chunks.length ? (
          <List
            size="small"
            dataSource={result.matched_chunks.slice(0, 3)}
            renderItem={(item) => (
              <List.Item>
                <Text>{objectText(item, 'quote') || '证据文本不可用'}</Text>
              </List.Item>
            )}
          />
        ) : (
          <Text type="secondary">暂无向量证据</Text>
        )}
      </section>

      {result.status === 'completed' && (
        <>
          <section>
            <Text strong>评分维度</Text>
            {result.ai_dimension_scores.length ? (
              <List
                size="small"
                dataSource={result.ai_dimension_scores}
                renderItem={(item) => (
                  <List.Item>
                    <div className="talent-recommendation-detail-line">
                      <Text strong>{objectText(item, 'name') || '未命名维度'}</Text>
                      <Text>{objectText(item, 'score') || '0'} 分</Text>
                      <Text type="secondary">{objectText(item, 'rationale')}</Text>
                    </div>
                  </List.Item>
                )}
              />
            ) : (
              <Text type="secondary">暂无维度评分</Text>
            )}
          </section>

          <section>
            <Text strong>硬性条件</Text>
            {result.ai_hard_requirement_results.length ? (
              <List
                size="small"
                dataSource={result.ai_hard_requirement_results}
                renderItem={(item) => (
                  <List.Item>
                    <div className="talent-recommendation-detail-line">
                      <Text>{objectText(item, 'title') || '硬性条件'}</Text>
                      <Tag>{objectText(item, 'status') || '待确认'}</Tag>
                      <Text type="secondary">{objectText(item, 'rationale')}</Text>
                    </div>
                  </List.Item>
                )}
              />
            ) : (
              <Text type="secondary">未配置硬性条件</Text>
            )}
          </section>

          <section className="talent-recommendation-insights">
            <div>
              <Text strong>优势</Text>
              <Paragraph>{result.ai_strengths.join('；') || '暂无'}</Paragraph>
            </div>
            <div>
              <Text strong>差距</Text>
              <Paragraph>{result.ai_gaps.join('；') || '暂无'}</Paragraph>
            </div>
            <div>
              <Text strong>缺失项</Text>
              <Paragraph>{result.ai_missing_items.join('；') || '暂无'}</Paragraph>
            </div>
          </section>

          <section>
            <Text strong>AI 证据</Text>
            {result.ai_evidence.length ? (
              <List
                size="small"
                dataSource={result.ai_evidence}
                renderItem={(item) => (
                  <List.Item>
                    <div className="talent-recommendation-detail-line">
                      <Text>{objectText(item, 'quote') || '证据文本不可用'}</Text>
                      <Text type="secondary">
                        {objectText(item, 'page_number')
                          ? `第 ${objectText(item, 'page_number')} 页`
                          : objectText(item, 'paragraph_index')
                            ? `第 ${objectText(item, 'paragraph_index')} 段`
                            : objectText(item, 'segment_key')}
                      </Text>
                    </div>
                  </List.Item>
                )}
              />
            ) : (
              <Text type="secondary">暂无 AI 证据</Text>
            )}
          </section>
        </>
      )}
    </div>
  )
}

export function TalentRecommendationPanel() {
  const auth = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [messageApi, messageContext] = message.useMessage()
  const [modal, modalContext] = Modal.useModal()
  const [groupIds, setGroupIds] = useState<string[]>()
  const [aiInputMode, setAiInputMode] = useState<'raw' | 'redacted'>('raw')
  const [selectedResultIds, setSelectedResultIds] = useState<string[]>([])
  const [selectionOutcome, setSelectionOutcome] =
    useState<TalentRecommendationSelectionRecord>()

  const jobId = searchParams.get('job_id') ?? ''
  const runId = searchParams.get('run_id') ?? ''
  const createOpen = searchParams.get('create') === '1'
  const runStatus = (searchParams.get('status') || undefined) as
    | TalentRecommendationRunStatus
    | undefined
  const createdById = searchParams.get('created_by') ?? undefined
  const createdFrom = searchParams.get('created_from') ?? ''
  const createdTo = searchParams.get('created_to') ?? ''
  const page = Math.max(1, Number(searchParams.get('page') || 1) || 1)
  const canWrite = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter'].includes(role),
  )

  function updateParams(values: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams)
    next.set('view', 'recommendations')
    Object.entries(values).forEach(([key, value]) => {
      if (value) next.set(key, value)
      else next.delete(key)
    })
    setSearchParams(next)
  }

  const jobs = useQuery({
    queryKey: ['jobs', true],
    queryFn: () => fetchJobs(true),
  })
  const selectedJob = jobs.data?.find((job) => job.id === jobId)
  const jobDetail = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId),
    enabled: Boolean(jobId),
  })
  const groups = useQuery({
    queryKey: ['talent-pool-groups', { status: 'active', limit: 100 }],
    queryFn: () => fetchTalentPoolGroups({ status: 'active', limit: 100 }),
    enabled: Boolean(canWrite),
  })
  const filters = useMemo(
    () => ({
      status: runStatus,
      createdById,
      createdFrom: createdFrom ? `${createdFrom}T00:00:00+08:00` : undefined,
      createdTo: createdTo ? `${createdTo}T23:59:59+08:00` : undefined,
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    }),
    [createdById, createdFrom, createdTo, page, runStatus],
  )
  const runs = useQuery({
    queryKey: ['talent-recommendations', jobId, filters],
    queryFn: () => fetchTalentRecommendations(jobId, filters),
    enabled: Boolean(jobId && selectedJob),
  })
  const detail = useQuery({
    queryKey: ['talent-recommendation', jobId, runId],
    queryFn: () => fetchTalentRecommendation(jobId, runId),
    enabled: Boolean(jobId && runId && selectedJob),
    refetchInterval: (query) =>
      isRunning(query.state.data?.status) ? POLL_INTERVAL_MS : false,
  })

  const creatorOptions = useMemo(() => {
    const byId = new Map<string, string>()
    runs.data?.items.forEach((run) => {
      if (run.created_by_id) {
        byId.set(
          run.created_by_id,
          run.created_by_display_name || run.created_by_username,
        )
      }
    })
    return Array.from(byId, ([value, label]) => ({ value, label }))
  }, [runs.data?.items])

  const confirmedCriteria = jobDetail.data?.criteria_versions
    .filter((version) => version.status === 'confirmed')
    .sort((left, right) => right.version_number - left.version_number)[0]
  const selectedGroupIds =
    groupIds ?? (createOpen ? (groups.data?.items ?? []).map((group) => group.id) : [])

  async function refreshRecommendations() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['talent-recommendations', jobId] }),
      queryClient.invalidateQueries({ queryKey: ['talent-recommendation', jobId] }),
    ])
  }

  const createMutation = useMutation({
    mutationFn: () => createTalentRecommendation(jobId, selectedGroupIds, aiInputMode),
    onSuccess: async (result) => {
      messageApi.success(
        result.reused_active_run ? '已打开正在执行的推荐任务' : '推荐任务已创建',
      )
      setGroupIds(undefined)
      setAiInputMode('raw')
      updateParams({ create: null, run_id: result.run.id, page: '1' })
      await refreshRecommendations()
    },
    onError: (error) => messageApi.error(errorMessage(error, '创建推荐任务失败')),
  })
  const cancelMutation = useMutation({
    mutationFn: (run: TalentRecommendationRunRecord) =>
      cancelTalentRecommendation(jobId, run.id, run.resource_version),
    onSuccess: async () => {
      messageApi.success('推荐任务已取消')
      await refreshRecommendations()
    },
    onError: (error) => messageApi.error(errorMessage(error, '取消推荐任务失败')),
  })
  const retryMutation = useMutation({
    mutationFn: (run: TalentRecommendationRunRecord) =>
      retryTalentRecommendationFailures(jobId, run.id, run.resource_version),
    onSuccess: async () => {
      messageApi.success('失败项已重新入队')
      await refreshRecommendations()
    },
    onError: (error) => messageApi.error(errorMessage(error, '重试失败项失败')),
  })
  const selectionMutation = useMutation({
    mutationFn: ({
      ids,
      confirmedIds,
    }: {
      ids: string[]
      confirmedIds: string[]
    }) =>
      selectTalentRecommendationCandidates(
        jobId,
        runId,
        ids,
        confirmedIds,
      ),
    onSuccess: async (result, variables) => {
      setSelectionOutcome(result)
      const staleIds = result.items
        .filter(
          (item) =>
            item.status === 'failed' && item.failure_code === 'primary_document_changed',
        )
        .map((item) => item.result_id)
      const alreadyConfirmed = new Set(variables.confirmedIds)
      const needsConfirmation = staleIds.filter((id) => !alreadyConfirmed.has(id))
      if (needsConfirmation.length) {
        modal.confirm({
          title: '候选人的主简历已经变化',
          content: `有 ${needsConfirmation.length} 位候选人的当前主简历与推荐时不同。是否继续使用本次推荐锁定的旧简历创建应聘？`,
          okText: '确认使用旧简历',
          cancelText: '暂不创建',
          onOk: () =>
            selectionMutation.mutate({
              ids: needsConfirmation,
              confirmedIds: needsConfirmation,
            }),
        })
      } else {
        messageApi.success(
          `已创建 ${result.created_count} 条应聘，${result.existing_count} 条已存在，${result.failed_count} 条失败`,
        )
      }
      setSelectedResultIds([])
      await refreshRecommendations()
    },
    onError: (error) => messageApi.error(errorMessage(error, '推荐候选人转应聘失败')),
  })

  function openRun(run: TalentRecommendationRunRecord) {
    setSelectedResultIds([])
    setSelectionOutcome(undefined)
    updateParams({ run_id: run.id, create: null })
  }

  function openCreate() {
    if (!jobId) {
      messageApi.warning('请先选择目标职位')
      return
    }
    setGroupIds(undefined)
    setAiInputMode('raw')
    updateParams({ create: '1', run_id: null })
  }

  function confirmCancel(run: TalentRecommendationRunRecord) {
    modal.confirm({
      title: '取消推荐任务？',
      content: '已经生成的结果会保留，但任务不会继续处理。',
      okText: '确认取消',
      cancelText: '继续处理',
      okButtonProps: { danger: true },
      onOk: () => cancelMutation.mutate(run),
    })
  }

  function confirmSelection() {
    modal.confirm({
      title: `将 ${selectedResultIds.length} 位候选人转为应聘？`,
      content: `系统会为“${detail.data?.job_title ?? selectedJob?.title ?? '当前职位'}”创建独立应聘和筛选结果，不会继承旧职位的人工判断。`,
      okText: '确认创建应聘',
      cancelText: '取消',
      onOk: () =>
        selectionMutation.mutate({ ids: selectedResultIds, confirmedIds: [] }),
    })
  }

  const runDetail = detail.data
  const selectable = runDetail?.allowed_actions.includes('select_candidates') ?? false
  const resultItems = (runDetail?.results ?? []).map((result) => {
    const aiMeta = result.ai_group ? aiGroupMeta[result.ai_group] : null
    const checked = selectedResultIds.includes(result.id)
    const canSelect = selectable && result.status === 'completed'
    return {
      key: result.id,
      label: (
        <div className="talent-recommendation-result-heading">
          <Checkbox
            aria-label={`选择 ${result.candidate_name || result.candidate_code}`}
            checked={checked}
            disabled={!canSelect}
            onClick={(event) => event.stopPropagation()}
            onChange={(event) => {
              setSelectedResultIds((current) =>
                event.target.checked
                  ? [...current, result.id].slice(0, 20)
                  : current.filter((id) => id !== result.id),
              )
            }}
          />
          <div>
            <Text strong>{result.candidate_name || '姓名待补充'}</Text>
            <Text type="secondary">{result.candidate_code}</Text>
          </div>
          <Space size={4} wrap>
            <Tag>{resultStatusLabel(result)}</Tag>
            {aiMeta && <Tag color={aiMeta.color}>{aiMeta.label}</Tag>}
            {result.document_stale && <Tag color="warning">简历已变化</Tag>}
            {result.candidate_merged_at && <Tag>档案已合并</Tag>}
          </Space>
          <div className="talent-recommendation-scores">
            <Text>AI {result.ai_score === null ? '--' : `${result.ai_score} 分`}</Text>
            <Text>相似度 {(result.similarity_score * 100).toFixed(1)}%</Text>
          </div>
        </div>
      ),
      children: (
        <>
          {(result.failure_message || result.exclusion_reason) && (
            <Alert
              type={result.status === 'failed' ? 'error' : 'warning'}
              showIcon
              message={result.failure_message || result.exclusion_reason}
              className="talent-recommendation-inline-alert"
            />
          )}
          <ResultEvidence result={result} />
        </>
      ),
    }
  })

  return (
    <section className="talent-page-section" aria-label="人才推荐任务">
      {messageContext}
      {modalContext}

      <div className="talent-recommendation-toolbar">
        <Select
          aria-label="选择推荐职位"
          showSearch
          allowClear
          optionFilterProp="label"
          placeholder="选择目标职位"
          loading={jobs.isPending}
          value={jobId || undefined}
          options={(jobs.data ?? []).map((job) => ({
            value: job.id,
            label: `${job.title}${job.status === 'archived' ? '（已归档）' : ''}`,
          }))}
          onChange={(value) =>
            updateParams({
              job_id: value ?? null,
              run_id: null,
              create: null,
              page: null,
            })
          }
        />
        <Select
          aria-label="筛选推荐任务状态"
          allowClear
          placeholder="全部状态"
          value={runStatus}
          options={Object.entries(runStatusMeta).map(([value, meta]) => ({
            value,
            label: meta.label,
          }))}
          onChange={(value) => updateParams({ status: value ?? null, page: null })}
        />
        <Select
          aria-label="筛选创建人"
          allowClear
          placeholder="全部创建人"
          value={createdById}
          options={creatorOptions}
          onChange={(value) => updateParams({ created_by: value ?? null, page: null })}
        />
        <Input
          aria-label="创建开始日期"
          type="date"
          value={createdFrom}
          onChange={(event) =>
            updateParams({ created_from: event.target.value || null, page: null })
          }
        />
        <Input
          aria-label="创建结束日期"
          type="date"
          value={createdTo}
          onChange={(event) =>
            updateParams({ created_to: event.target.value || null, page: null })
          }
        />
        <Button
          aria-label="刷新推荐任务"
          icon={<ReloadOutlined />}
          loading={runs.isFetching}
          disabled={!jobId}
          onClick={() => void refreshRecommendations()}
        />
        {canWrite && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!jobId || selectedJob?.status === 'archived'}
            onClick={openCreate}
          >
            新建推荐任务
          </Button>
        )}
      </div>

      {!jobId && <Empty description="选择一个职位后查看推荐任务" />}
      {jobId && jobs.isSuccess && !selectedJob && (
        <Alert
          type="warning"
          showIcon
          message="职位不存在或不在当前账号的数据范围内"
          action={<Button onClick={() => updateParams({ job_id: null })}>清除职位</Button>}
        />
      )}
      {runs.isError && (
        <Alert
          type="error"
          showIcon
          message="人才推荐任务读取失败"
          description={errorMessage(runs.error, '请稍后重试')}
        />
      )}
      {jobId && selectedJob && (
        <List
          className="talent-recommendation-list"
          loading={runs.isPending}
          dataSource={runs.data?.items ?? []}
          locale={{ emptyText: <Empty description="该职位还没有推荐任务" /> }}
          pagination={
            (runs.data?.total ?? 0) > PAGE_SIZE
              ? {
                  current: page,
                  pageSize: PAGE_SIZE,
                  total: runs.data?.total,
                  showSizeChanger: false,
                  onChange: (nextPage) => updateParams({ page: String(nextPage) }),
                }
              : false
          }
          renderItem={(run) => {
            const meta = runStatusMeta[run.status]
            return (
              <List.Item
                actions={[
                  <Button
                    key="detail"
                    type="text"
                    icon={<EyeOutlined />}
                    onClick={() => openRun(run)}
                  >
                    查看
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  avatar={<TeamOutlined className="talent-recommendation-list-icon" />}
                  title={
                    <Space wrap>
                      <Text strong>标准 V{run.criteria_version_number}</Text>
                      <Tag color={meta.color}>{meta.label}</Tag>
                      {run.criteria_stale && <Tag color="warning">标准已过期</Tag>}
                    </Space>
                  }
                  description={
                    <div className="talent-recommendation-list-meta">
                      <Text type="secondary">
                        {run.groups.map((group) => group.group_name).join('、')}
                      </Text>
                      <Text type="secondary">
                        {run.created_by_display_name || run.created_by_username} ·{' '}
                        {formatDateTime(run.created_at)}
                      </Text>
                      <Text type="secondary">
                        召回 {run.retrieved_count}/{run.recall_limit} · AI 完成{' '}
                        {run.completed_count}/{run.rescore_limit} · 失败 {run.failed_count}
                      </Text>
                    </div>
                  }
                />
              </List.Item>
            )
          }}
        />
      )}

      <Modal
        open={createOpen}
        title="新建人才推荐任务"
        okText="开始推荐"
        cancelText="取消"
        confirmLoading={createMutation.isPending}
        okButtonProps={{
          disabled:
            !jobId ||
            !confirmedCriteria ||
            !selectedGroupIds.length ||
            selectedJob?.status === 'archived',
        }}
        onOk={() => createMutation.mutate()}
        onCancel={() => {
          setGroupIds(undefined)
          updateParams({ create: null })
        }}
        destroyOnHidden
      >
        <div className="talent-recommendation-create-form">
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="目标职位">
              {selectedJob?.title || '职位不可用'}
            </Descriptions.Item>
            <Descriptions.Item label="筛选标准">
              {confirmedCriteria ? `已确认 V${confirmedCriteria.version_number}` : '尚未确认'}
            </Descriptions.Item>
          </Descriptions>
          {!confirmedCriteria && !jobDetail.isPending && (
            <Alert type="warning" showIcon message="请先确认该职位的筛选标准" />
          )}
          <label>
            <Text strong>人才分组</Text>
            <Select
              aria-label="选择人才分组"
              mode="multiple"
              placeholder="选择一个或多个人才分组"
              loading={groups.isPending}
              value={selectedGroupIds}
              options={(groups.data?.items ?? []).map((group) => ({
                value: group.id,
                label: `${group.name}（${group.member_count} 人）`,
              }))}
              onChange={setGroupIds}
            />
          </label>
          <label>
            <Text strong>AI 使用文本</Text>
            <Segmented<'raw' | 'redacted'>
              aria-label="AI 使用文本"
              block
              value={aiInputMode}
              options={[
                { value: 'raw', label: '解析原文' },
                { value: 'redacted', label: '本地脱敏文本' },
              ]}
              onChange={setAiInputMode}
            />
          </label>
          <Alert
            type="info"
            showIcon
            message="最多召回 50 人，仅前 20 人执行 AI 重评"
            description="推荐结果只供招聘专员预览，不会自动创建应聘或推进候选人流程。任务创建后不能修改输入策略。"
          />
        </div>
      </Modal>

      <Drawer
        className="talent-recommendation-drawer"
        open={Boolean(runId)}
        width={820}
        title={runDetail ? `${runDetail.job_title} · 人才推荐` : '人才推荐详情'}
        onClose={() => {
          setSelectedResultIds([])
          setSelectionOutcome(undefined)
          updateParams({ run_id: null })
        }}
        extra={
          runDetail && (
            <Space wrap>
              {runDetail.allowed_actions.includes('cancel') && (
                <Button
                  danger
                  icon={<StopOutlined />}
                  loading={cancelMutation.isPending}
                  onClick={() => confirmCancel(runDetail)}
                >
                  取消任务
                </Button>
              )}
              {runDetail.allowed_actions.includes('retry_failed_items') && (
                <Button
                  icon={<SyncOutlined />}
                  loading={retryMutation.isPending}
                  onClick={() => retryMutation.mutate(runDetail)}
                >
                  重试失败项
                </Button>
              )}
            </Space>
          )
        }
      >
        {detail.isPending && <List loading dataSource={[]} />}
        {detail.isError && (
          <Alert
            type="error"
            showIcon
            message="推荐任务详情读取失败"
            description={errorMessage(detail.error, '任务不存在或已不可见')}
            action={<Button onClick={() => void detail.refetch()}>重试</Button>}
          />
        )}
        {runDetail && (
          <div className="talent-recommendation-detail">
            {runDetail.criteria_stale && (
              <Alert
                type="warning"
                showIcon
                message="职位筛选标准已经更新"
                description="该任务结果仍可查看，但不能转为应聘。请使用最新确认标准创建新任务。"
              />
            )}
            {runDetail.failure_summary && (
              <Alert
                type={runDetail.status === 'failed' ? 'error' : 'warning'}
                showIcon
                message="任务处理说明"
                description={runDetail.failure_summary}
              />
            )}
            <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
              <Descriptions.Item label="任务状态">
                <Tag color={runStatusMeta[runDetail.status].color}>
                  {runStatusMeta[runDetail.status].label}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="筛选标准">
                V{runDetail.criteria_version_number}
              </Descriptions.Item>
              <Descriptions.Item label="人才范围">
                {runDetail.scope_candidate_count} 人
              </Descriptions.Item>
              <Descriptions.Item label="处理计数">
                召回 {runDetail.retrieved_count} · 完成 {runDetail.completed_count} · 失败{' '}
                {runDetail.failed_count} · 排除 {runDetail.excluded_count}
              </Descriptions.Item>
              <Descriptions.Item label="AI 输入">
                {runDetail.ai_input_mode === 'raw' ? '解析原文' : '本地脱敏文本'}
              </Descriptions.Item>
              <Descriptions.Item label="人才分组">
                {runDetail.groups.map((group) => group.group_name).join('、')}
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {formatDateTime(runDetail.created_at)}
              </Descriptions.Item>
              <Descriptions.Item label="完成时间">
                {formatDateTime(runDetail.completed_at)}
              </Descriptions.Item>
            </Descriptions>

            <div className="talent-recommendation-selection-bar">
              <div>
                <Title level={4}>候选人结果</Title>
                <Text type="secondary">
                  AI 分数与向量相似度是两种独立信号；只有 AI 重评完成项可以转为应聘。
                </Text>
              </div>
              {selectable && (
                <Button
                  type="primary"
                  icon={<CheckCircleOutlined />}
                  disabled={!selectedResultIds.length}
                  loading={selectionMutation.isPending}
                  onClick={confirmSelection}
                >
                  转为应聘（{selectedResultIds.length}/20）
                </Button>
              )}
            </div>

            {resultItems.length ? (
              <Collapse className="talent-recommendation-results" items={resultItems} />
            ) : (
              <Empty description={isRunning(runDetail.status) ? '任务正在处理' : '没有推荐结果'} />
            )}

            {selectionOutcome && (
              <section className="talent-recommendation-selection-outcome">
                <Title level={4}>转应聘结果</Title>
                <List
                  size="small"
                  dataSource={selectionOutcome.items}
                  renderItem={(item) => (
                    <List.Item
                      actions={
                        item.application_id
                          ? [
                              <Button
                                key="application"
                                type="link"
                                onClick={() =>
                                  navigate(
                                    `/jobs/${encodeURIComponent(jobId)}/pipeline?application_id=${encodeURIComponent(item.application_id!)}`,
                                  )
                                }
                              >
                                查看候选人流程
                              </Button>,
                            ]
                          : undefined
                      }
                    >
                      <Space>
                        {item.status === 'failed' ? (
                          <CloseCircleOutlined className="status-error-icon" />
                        ) : (
                          <CheckCircleOutlined className="status-success-icon" />
                        )}
                        <Text>{selectionStatusLabel(item.status)}</Text>
                        {item.failure_message && (
                          <Text type="secondary">{item.failure_message}</Text>
                        )}
                      </Space>
                    </List.Item>
                  )}
                />
              </section>
            )}
          </div>
        )}
      </Drawer>
    </section>
  )
}
