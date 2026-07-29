import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  InboxOutlined,
  ReloadOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Empty,
  Pagination,
  Select,
  Skeleton,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import {
  fetchWorkbenchItems,
  fetchWorkbenchSummary,
  type WorkbenchItemRecord,
  type WorkbenchItemType,
  type WorkbenchListRecord,
  type WorkbenchPriority,
  type WorkbenchSection,
  type WorkbenchSource,
} from '../api/client'
import { withWorkbenchReturnTo } from '../components/navigation'

const { Title, Text } = Typography
const PAGE_SIZE = 6
const SCROLL_STORAGE_KEY = 'smarthr:workbench-scroll'
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

const sectionMeta: Record<
  WorkbenchSection,
  { title: string; description: string; icon: ReactNode; tone: string; action: string }
> = {
  action_required: {
    title: '需要我处理',
    description: '完成源业务操作后，对应事项会自动消失',
    icon: <CheckCircleOutlined />,
    tone: 'action',
    action: '去处理',
  },
  waiting_external: {
    title: '等待外部回应',
    description: '候选人尚未回应，暂时无需内部操作',
    icon: <ClockCircleOutlined />,
    tone: 'waiting',
    action: '查看详情',
  },
  risk_failure: {
    title: '风险与失败',
    description: '存在临近期限或系统处理异常的事项',
    icon: <WarningOutlined />,
    tone: 'risk',
    action: '查看异常',
  },
}

const priorityMeta: Record<WorkbenchPriority, { label: string; color: string }> = {
  urgent: { label: '紧急', color: 'error' },
  high: { label: '高', color: 'warning' },
  normal: { label: '普通', color: 'default' },
}

const itemTypeLabels: Record<WorkbenchItemType, string> = {
  recruitment_request_revision: '招聘需求补充',
  recruitment_request_approval: '招聘需求审批',
  manual_screening: '人工初筛',
  interview_scheduling: '面试安排',
  interview_evaluation: '面试评价',
  interview_report: '面试报告',
  offer_manager_confirmation: '录用确认',
  offer_approval: 'Offer 审批',
  offer_link: 'Offer 链接',
  onboarding_date: '入职日期',
  onboarding_outcome: '入职结果',
  system_failure: '系统处理失败',
  temporary_password_account: '临时密码账号',
}

const sourceLabels: Record<WorkbenchSource, string> = {
  recruitment_requests: '招聘需求',
  screening: '智能筛选',
  interviews: '面试',
  offers: 'Offer',
  onboardings: '入职',
  system_failures: '异步任务',
  accounts: '账号',
}

function pageFrom(searchParams: URLSearchParams, key: string) {
  const value = Number(searchParams.get(key))
  return Number.isInteger(value) && value > 0 ? value : 1
}

function pageKey(section: WorkbenchSection) {
  if (section === 'action_required') return 'actionPage'
  if (section === 'waiting_external') return 'waitingPage'
  return 'riskPage'
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function sectionCount(
  sections: Array<{ section: WorkbenchSection; count: number }> | undefined,
  section: WorkbenchSection,
) {
  return sections?.find((item) => item.section === section)?.count ?? 0
}

function priorityCount(
  priorities: Array<{ priority: WorkbenchPriority; count: number }> | undefined,
  priority: WorkbenchPriority,
) {
  return priorities?.find((item) => item.priority === priority)?.count ?? 0
}

interface WorkbenchSectionPanelProps {
  section: WorkbenchSection
  result: WorkbenchListRecord | undefined
  pending: boolean
  error: Error | null
  page: number
  onPageChange: (page: number) => void
  onOpen: (item: WorkbenchItemRecord) => void
  onRetry: () => void
}

function WorkbenchSectionPanel({
  section,
  result,
  pending,
  error,
  page,
  onPageChange,
  onOpen,
  onRetry,
}: WorkbenchSectionPanelProps) {
  const meta = sectionMeta[section]

  return (
    <section className={`workbench-section workbench-section--${meta.tone}`}>
      <div className="workbench-section-heading">
        <div className="workbench-section-title">
          <span className="workbench-section-icon" aria-hidden="true">
            {meta.icon}
          </span>
          <div>
            <Space size="small">
              <Title level={3}>{meta.title}</Title>
              <Tag>{result?.total ?? 0}</Tag>
            </Space>
            <Text type="secondary">{meta.description}</Text>
          </div>
        </div>
      </div>

      {pending && <Skeleton active paragraph={{ rows: 3 }} className="workbench-skeleton" />}
      {error && (
        <Alert
          type="error"
          showIcon
          message={`${meta.title}读取失败`}
          description={error.message}
          action={<Button onClick={onRetry}>重试</Button>}
        />
      )}
      {!pending && !error && result?.items.length === 0 && (
        <Empty
          className="workbench-empty"
          image={<InboxOutlined />}
          description="当前筛选条件下没有事项"
        />
      )}
      {!pending && !error && Boolean(result?.items.length) && (
        <ul className="workbench-item-list">
          {result!.items.map((item) => (
            <li key={item.stable_key} className="workbench-item">
              <div className="workbench-item-main">
                <Space size={[6, 6]} wrap>
                  <Tag color={priorityMeta[item.priority].color}>
                    {priorityMeta[item.priority].label}
                  </Tag>
                  <Tag bordered={false}>{itemTypeLabels[item.item_type]}</Tag>
                  {item.job_title && <Text type="secondary">{item.job_title}</Text>}
                </Space>
                <Text strong className="workbench-item-title">
                  {item.title}
                </Text>
                <Text type="secondary">{item.summary}</Text>
              </div>
              <div className="workbench-item-meta">
                <Text type="secondary">产生于 {formatDateTime(item.occurred_at)}</Text>
                {item.risk_at && (
                  <Text className="workbench-risk-time">
                    <ExclamationCircleOutlined /> 风险时间 {formatDateTime(item.risk_at)}
                  </Text>
                )}
              </div>
              <Button
                type="link"
                className="workbench-item-action"
                aria-label={`${meta.action}：${item.title}`}
                icon={<ArrowRightOutlined />}
                iconPosition="end"
                onClick={() => onOpen(item)}
              >
                <span className="workbench-action-label">{meta.action}</span>
              </Button>
            </li>
          ))}
        </ul>
      )}

      {!pending && !error && (result?.total ?? 0) > PAGE_SIZE && (
        <Pagination
          className="workbench-pagination"
          current={page}
          pageSize={PAGE_SIZE}
          total={result?.total ?? 0}
          showSizeChanger={false}
          onChange={onPageChange}
        />
      )}
    </section>
  )
}

export function WorkbenchPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const restoredScroll = useRef(false)
  const itemTypeParam = searchParams.get('type')
  const priorityParam = searchParams.get('priority')
  const jobParam = searchParams.get('job')
  const itemType =
    itemTypeParam && Object.hasOwn(itemTypeLabels, itemTypeParam)
      ? (itemTypeParam as WorkbenchItemType)
      : undefined
  const priority =
    priorityParam && Object.hasOwn(priorityMeta, priorityParam)
      ? (priorityParam as WorkbenchPriority)
      : undefined
  const jobId = jobParam && UUID_PATTERN.test(jobParam) ? jobParam : undefined
  const actionPage = pageFrom(searchParams, 'actionPage')
  const waitingPage = pageFrom(searchParams, 'waitingPage')
  const riskPage = pageFrom(searchParams, 'riskPage')

  const summary = useQuery({
    queryKey: ['workbench', 'summary'],
    queryFn: fetchWorkbenchSummary,
    refetchInterval: 60_000,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
  })

  const commonFilters = { itemType, priority, jobId, pageSize: PAGE_SIZE }
  const actionItems = useQuery({
    queryKey: ['workbench', 'items', 'action_required', commonFilters, actionPage],
    queryFn: () =>
      fetchWorkbenchItems({
        ...commonFilters,
        section: 'action_required',
        page: actionPage,
      }),
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
  })
  const waitingItems = useQuery({
    queryKey: ['workbench', 'items', 'waiting_external', commonFilters, waitingPage],
    queryFn: () =>
      fetchWorkbenchItems({
        ...commonFilters,
        section: 'waiting_external',
        page: waitingPage,
      }),
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
  })
  const riskItems = useQuery({
    queryKey: ['workbench', 'items', 'risk_failure', commonFilters, riskPage],
    queryFn: () =>
      fetchWorkbenchItems({
        ...commonFilters,
        section: 'risk_failure',
        page: riskPage,
      }),
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
  })

  const allQueriesSettled =
    !summary.isPending && !actionItems.isPending && !waitingItems.isPending && !riskItems.isPending

  useEffect(() => {
    if (restoredScroll.current || !allQueriesSettled) return
    restoredScroll.current = true
    const saved = Number(sessionStorage.getItem(SCROLL_STORAGE_KEY))
    sessionStorage.removeItem(SCROLL_STORAGE_KEY)
    if (!Number.isFinite(saved) || saved <= 0) return
    window.requestAnimationFrame(() => window.scrollTo({ top: saved, behavior: 'instant' }))
  }, [allQueriesSettled])

  const failedSources = useMemo(() => {
    const sources = [
      ...(summary.data?.failed_sources ?? []),
      ...(actionItems.data?.failed_sources ?? []),
      ...(waitingItems.data?.failed_sources ?? []),
      ...(riskItems.data?.failed_sources ?? []),
    ]
    return [...new Set(sources)]
  }, [summary.data, actionItems.data, waitingItems.data, riskItems.data])

  function setFilter(key: 'type' | 'priority' | 'job', value?: string) {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete('actionPage')
    next.delete('waitingPage')
    next.delete('riskPage')
    setSearchParams(next, { replace: true })
  }

  function setPage(section: WorkbenchSection, page: number) {
    const next = new URLSearchParams(searchParams)
    const key = pageKey(section)
    if (page > 1) next.set(key, String(page))
    else next.delete(key)
    setSearchParams(next, { replace: true })
  }

  function clearFilters() {
    setSearchParams({}, { replace: true })
  }

  function openItem(item: WorkbenchItemRecord) {
    sessionStorage.setItem(SCROLL_STORAGE_KEY, String(window.scrollY))
    const returnTo = `${location.pathname}${location.search}`
    navigate(withWorkbenchReturnTo(item.target_path, returnTo))
  }

  function refreshAll() {
    void Promise.all([
      summary.refetch(),
      actionItems.refetch(),
      waitingItems.refetch(),
      riskItems.refetch(),
    ])
  }

  const hasFilters = Boolean(itemType || priority || jobId)

  return (
    <>
      <div className="page-heading workbench-heading">
        <div>
          <Title level={2}>招聘工作台</Title>
          <Text type="secondary">聚合当前业务事实，处理完成后待办自动更新</Text>
        </div>
        <Space wrap>
          {summary.data && (
            <Text type="secondary">统计于 {formatDateTime(summary.data.as_of)}</Text>
          )}
          <Tooltip title="刷新工作台">
            <Button
              aria-label="刷新工作台"
              icon={<ReloadOutlined />}
              loading={summary.isFetching}
              onClick={refreshAll}
            />
          </Tooltip>
        </Space>
      </div>

      {summary.isError && (
        <Alert
          type="error"
          showIcon
          className="page-alert"
          message="工作台摘要读取失败"
          description={summary.error.message}
          action={<Button onClick={() => void summary.refetch()}>重试</Button>}
        />
      )}
      {failedSources.length > 0 && (
        <Alert
          type="warning"
          showIcon
          className="page-alert"
          message="部分数据暂不可用"
          description={`未能读取：${failedSources.map((source) => sourceLabels[source]).join('、')}。其余数字与事项仍为真实结果。`}
        />
      )}

      <section className="workbench-summary" aria-label="工作台摘要">
        {summary.isPending ? (
          <Skeleton active paragraph={{ rows: 2 }} />
        ) : (
          <>
            <div className="workbench-primary-metric">
              <Text>需要我处理</Text>
              <strong>{summary.data?.action_required_count ?? 0}</strong>
              <Text type="secondary">项当前可执行事项</Text>
            </div>
            <div className="workbench-metric">
              <Text type="secondary">全部事项</Text>
              <strong>{summary.data?.total_count ?? 0}</strong>
            </div>
            <div className="workbench-metric workbench-metric--urgent">
              <Text type="secondary">紧急</Text>
              <strong>{priorityCount(summary.data?.priorities, 'urgent')}</strong>
            </div>
            <div className="workbench-metric workbench-metric--high">
              <Text type="secondary">高优先级</Text>
              <strong>{priorityCount(summary.data?.priorities, 'high')}</strong>
            </div>
            <div className="workbench-metric workbench-metric--waiting">
              <Text type="secondary">等待回应</Text>
              <strong>{sectionCount(summary.data?.sections, 'waiting_external')}</strong>
            </div>
          </>
        )}
      </section>

      <section className="workbench-filters" aria-label="工作台筛选">
        <Select
          aria-label="按事项类型筛选"
          allowClear
          placeholder="全部事项类型"
          value={itemType}
          options={(summary.data?.types ?? []).map((item) => ({
            value: item.item_type,
            label: `${itemTypeLabels[item.item_type]}（${item.count}）`,
          }))}
          onChange={(value) => setFilter('type', value)}
        />
        <Select
          aria-label="按优先级筛选"
          allowClear
          placeholder="全部优先级"
          value={priority}
          options={(Object.keys(priorityMeta) as WorkbenchPriority[]).map((value) => ({
            value,
            label: priorityMeta[value].label,
          }))}
          onChange={(value) => setFilter('priority', value)}
        />
        <Select
          aria-label="按岗位筛选"
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="全部岗位"
          value={jobId}
          options={(summary.data?.jobs ?? []).map((job) => ({ value: job.id, label: job.title }))}
          onChange={(value) => setFilter('job', value)}
        />
        {hasFilters && <Button onClick={clearFilters}>清除筛选</Button>}
      </section>

      <div className="workbench-sections">
        <WorkbenchSectionPanel
          section="action_required"
          result={actionItems.data}
          pending={actionItems.isPending}
          error={actionItems.error}
          page={actionPage}
          onPageChange={(page) => setPage('action_required', page)}
          onOpen={openItem}
          onRetry={() => void actionItems.refetch()}
        />
        <WorkbenchSectionPanel
          section="waiting_external"
          result={waitingItems.data}
          pending={waitingItems.isPending}
          error={waitingItems.error}
          page={waitingPage}
          onPageChange={(page) => setPage('waiting_external', page)}
          onOpen={openItem}
          onRetry={() => void waitingItems.refetch()}
        />
        <WorkbenchSectionPanel
          section="risk_failure"
          result={riskItems.data}
          pending={riskItems.isPending}
          error={riskItems.error}
          page={riskPage}
          onPageChange={(page) => setPage('risk_failure', page)}
          onOpen={openItem}
          onRetry={() => void riskItems.refetch()}
        />
      </div>
    </>
  )
}
