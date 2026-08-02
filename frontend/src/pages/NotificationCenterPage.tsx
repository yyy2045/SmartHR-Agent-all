import {
  ArrowRightOutlined,
  BellOutlined,
  CheckOutlined,
  InboxOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Empty, Pagination, Select, Skeleton, Space, Tag, Typography } from 'antd'
import { useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  ApiError,
  fetchInternalNotifications,
  markAllInternalNotificationsRead,
  markInternalNotificationRead,
  type InternalNotificationReadStatus,
  type InternalNotificationRecord,
} from '../api/client'

const { Text, Title } = Typography
const PAGE_SIZE = 10

const notificationTypeLabels: Record<string, string> = {
  recruitment_request_submitted: '需求待审批',
  recruitment_request_approved: '需求已批准',
  recruitment_request_rejected: '需求已驳回',
  offer_manager_confirmation_requested: 'Offer 待确认',
  offer_approval_requested: 'Offer 待审批',
  offer_approved: 'Offer 已批准',
  offer_rejected: 'Offer 已驳回',
  offer_candidate_accepted: '候选人接受 Offer',
  offer_candidate_rejected: '候选人拒绝 Offer',
  onboarding_date_changed: '入职日期',
  onboarding_completed: '已入职',
  onboarding_abandoned: '放弃入职',
}

function pageFrom(searchParams: URLSearchParams) {
  const value = Number(searchParams.get('page'))
  return Number.isInteger(value) && value > 0 ? value : 1
}

function statusFrom(searchParams: URLSearchParams): InternalNotificationReadStatus {
  const value = searchParams.get('status')
  return value === 'unread' || value === 'read' ? value : 'all'
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function labelForType(type: string) {
  return notificationTypeLabels[type] ?? type
}

function notificationTone(type: string) {
  if (type.includes('rejected') || type.includes('abandoned')) return 'error'
  if (type.includes('approved') || type.includes('accepted') || type.includes('completed')) {
    return 'success'
  }
  if (type.includes('requested') || type.includes('submitted')) return 'processing'
  return 'default'
}

export function NotificationCenterPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const status = statusFrom(searchParams)
  const type = searchParams.get('type') || undefined
  const page = pageFrom(searchParams)
  const offset = (page - 1) * PAGE_SIZE

  const notifications = useQuery({
    queryKey: ['notifications', { status, type, page }],
    queryFn: () =>
      fetchInternalNotifications({
        status,
        notificationType: type,
        limit: PAGE_SIZE,
        offset,
      }),
    staleTime: 15_000,
  })

  const typeOptions = useMemo(() => {
    const known = Object.entries(notificationTypeLabels).map(([value, label]) => ({
      value,
      label,
    }))
    const dynamic =
      notifications.data?.items
        .filter((item) => !Object.hasOwn(notificationTypeLabels, item.notification_type))
        .map((item) => ({ value: item.notification_type, label: item.notification_type })) ?? []
    return [...known, ...dynamic]
  }, [notifications.data?.items])

  const invalidateNotifications = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['notifications'] }),
      queryClient.invalidateQueries({ queryKey: ['notifications', 'unread-count'] }),
    ])
  }

  const markReadMutation = useMutation({
    mutationFn: markInternalNotificationRead,
    onSuccess: invalidateNotifications,
  })

  const markAllMutation = useMutation({
    mutationFn: markAllInternalNotificationsRead,
    onSuccess: invalidateNotifications,
  })

  function updateFilters(next: {
    status?: InternalNotificationReadStatus
    type?: string | null
    page?: number
  }) {
    const params = new URLSearchParams(searchParams)
    const nextStatus = next.status ?? status
    if (nextStatus === 'all') params.delete('status')
    else params.set('status', nextStatus)
    if (next.type === null) params.delete('type')
    else if (next.type !== undefined) params.set('type', next.type)
    params.set('page', String(next.page ?? 1))
    if (params.get('page') === '1') params.delete('page')
    setSearchParams(params)
  }

  async function openNotification(item: InternalNotificationRecord) {
    if (!item.read_at) {
      try {
        await markReadMutation.mutateAsync(item.id)
      } catch {
        // 跳转仍然保留，避免已读状态失败阻断业务处理。
      }
    }
    navigate(item.route_path)
  }

  return (
    <div className="notification-center-page">
      <section className="notification-hero">
        <div>
          <Space size="small" wrap>
            <BellOutlined className="notification-hero-icon" />
            <Title level={2}>消息中心</Title>
            <Tag color={notifications.data?.unread_count ? 'processing' : 'default'}>
              未读 {notifications.data?.unread_count ?? 0}
            </Tag>
          </Space>
          <Text type="secondary">
            汇总招聘需求、Offer、候选人回应和入职流转提醒，点击消息可跳转到对应业务页面。
          </Text>
        </div>
        <Space wrap>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => void notifications.refetch()}
            loading={notifications.isFetching}
          >
            刷新
          </Button>
          <Button
            type="primary"
            icon={<CheckOutlined />}
            disabled={!notifications.data?.unread_count}
            loading={markAllMutation.isPending}
            onClick={() => markAllMutation.mutate()}
          >
            全部标记已读
          </Button>
        </Space>
      </section>

      <section className="notification-toolbar">
        <Select
          aria-label="筛选已读状态"
          value={status}
          options={[
            { value: 'all', label: '全部消息' },
            { value: 'unread', label: '只看未读' },
            { value: 'read', label: '只看已读' },
          ]}
          onChange={(value) => updateFilters({ status: value })}
        />
        <Select
          allowClear
          showSearch
          aria-label="筛选通知类型"
          placeholder="通知类型"
          value={type}
          options={typeOptions}
          optionFilterProp="label"
          onChange={(value) => updateFilters({ type: value ?? null })}
        />
      </section>

      {notifications.isPending && <Skeleton active paragraph={{ rows: 6 }} />}
      {notifications.isError && (
        <Alert
          type="error"
          showIcon
          message="无法读取站内通知"
          description={
            notifications.error instanceof ApiError ? notifications.error.message : '请稍后重试'
          }
          action={<Button onClick={() => void notifications.refetch()}>重试</Button>}
        />
      )}
      {!notifications.isPending && !notifications.isError && notifications.data?.items.length === 0 && (
        <Empty
          className="notification-empty"
          image={<InboxOutlined />}
          description="当前筛选条件下没有消息"
        />
      )}
      {!notifications.isPending && !notifications.isError && Boolean(notifications.data?.items.length) && (
        <ul className="notification-list">
          {notifications.data!.items.map((item) => (
            <li
              key={item.id}
              className={`notification-item${item.read_at ? '' : ' is-unread'}`}
            >
              <button
                type="button"
                className="notification-item-main"
                onClick={() => void openNotification(item)}
              >
                <Space size={[6, 6]} wrap>
                  <Tag color={notificationTone(item.notification_type)}>
                    {labelForType(item.notification_type)}
                  </Tag>
                  {!item.read_at && <Tag color="blue">未读</Tag>}
                  <Text type="secondary">{formatDateTime(item.created_at)}</Text>
                </Space>
                <Text strong className="notification-title">
                  {item.title}
                </Text>
                <Text type="secondary">{item.summary || '暂无摘要'}</Text>
              </button>
              <Space className="notification-actions">
                {!item.read_at && (
                  <Button
                    size="small"
                    onClick={() => markReadMutation.mutate(item.id)}
                    loading={markReadMutation.isPending}
                  >
                    标记已读
                  </Button>
                )}
                <Button
                  type="link"
                  icon={<ArrowRightOutlined />}
                  iconPosition="end"
                  onClick={() => void openNotification(item)}
                >
                  查看
                </Button>
              </Space>
            </li>
          ))}
        </ul>
      )}

      {!notifications.isPending && !notifications.isError && (notifications.data?.total ?? 0) > PAGE_SIZE && (
        <Pagination
          className="notification-pagination"
          current={page}
          pageSize={PAGE_SIZE}
          total={notifications.data?.total ?? 0}
          showSizeChanger={false}
          onChange={(nextPage) => updateFilters({ page: nextPage })}
        />
      )}
    </div>
  )
}
