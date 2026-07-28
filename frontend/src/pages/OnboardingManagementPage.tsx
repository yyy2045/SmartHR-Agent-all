import {
  ArrowLeftOutlined,
  CheckOutlined,
  CopyOutlined,
  EditOutlined,
  LinkOutlined,
  ReloadOutlined,
  StopOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Segmented,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMemo, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import {
  ApiError,
  abandonOnboarding,
  correctOnboardingStatus,
  createOnboardingPortalLink,
  decideOnboardingDate,
  fetchOfferPortalLinks,
  fetchOnboarding,
  fetchOnboardings,
  markOnboardingCompleted,
  regenerateOnboardingPortalLink,
  type OnboardingAbandonmentReason,
  type OnboardingAbandonmentSource,
  type OnboardingDetailRecord,
  type OnboardingEventAction,
  type OnboardingStatus,
  type OnboardingSummaryRecord,
} from '../api/client'
import { useAuth } from '../auth/context'
import { HiringModuleNav } from '../components/HiringModuleNav'

const { Title, Text } = Typography

type StatusFilter = 'all' | 'pending_confirmation' | 'pending_start' | 'onboarded' | 'abandoned'
type DialogKind = 'propose' | 'onboard' | 'abandon' | 'correct' | 'regenerate-link'

interface ActionValues {
  date?: string
  note?: string
  source?: OnboardingAbandonmentSource
  reasonCode?: OnboardingAbandonmentReason
}

const statusMeta: Record<OnboardingStatus, { label: string; color: string }> = {
  pending_confirmation: { label: '待候选人确认', color: 'processing' },
  candidate_proposed_date: { label: '待招聘方确认', color: 'warning' },
  pending_start: { label: '待入职', color: 'cyan' },
  onboarded: { label: '已入职', color: 'success' },
  abandoned: { label: '已放弃', color: 'default' },
}

const sourceLabels: Record<OnboardingAbandonmentSource, string> = {
  candidate_withdrew: '候选人放弃',
  company_cancelled: '公司取消',
  other: '其他',
}

const reasonLabels: Record<OnboardingAbandonmentReason, string> = {
  compensation: '薪酬原因',
  career: '职业发展',
  location: '工作地点',
  start_date: '入职日期',
  personal: '个人原因',
  position_cancelled: '职位取消',
  business_change: '业务调整',
  other: '其他',
}

const eventLabels: Record<OnboardingEventAction, string> = {
  created: '建立入职记录',
  candidate_confirmed_date: '候选人确认日期',
  candidate_proposed_date: '候选人提出日期',
  recruiter_accepted_date: '招聘方接受日期',
  recruiter_proposed_date: '招聘方提出日期',
  onboarded: '标记已入职',
  abandoned: '标记放弃入职',
  onboarded_corrected: '更正已入职状态',
}

function formatDate(value: string | null) {
  if (!value) return '未确定'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(`${value}T00:00:00`))
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function today() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function belongsToFilter(status: OnboardingStatus, filter: StatusFilter) {
  if (filter === 'all') return true
  if (filter === 'pending_confirmation') {
    return status === 'pending_confirmation' || status === 'candidate_proposed_date'
  }
  return status === filter
}

function currentDate(record: OnboardingSummaryRecord) {
  return (
    record.actual_start_date ??
    record.confirmed_start_date ??
    record.candidate_proposed_date ??
    record.recruiter_proposed_date ??
    record.expected_start_date
  )
}

function safeInternalPath(value: string | null) {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return undefined
  try {
    const resolved = new URL(value, window.location.origin)
    if (resolved.origin !== window.location.origin) return undefined
    return `${resolved.pathname}${resolved.search}${resolved.hash}`
  } catch {
    return undefined
  }
}

function returnLabel(path: string) {
  if (path.startsWith('/offers')) return '返回 Offer 详情'
  if (path.includes('/pipeline')) return '返回候选人流程'
  return '返回来源页面'
}

export function OnboardingManagementPage() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const [messageApi, messageContext] = message.useMessage()
  const [modal, modalContext] = Modal.useModal()
  const [form] = Form.useForm<ActionValues>()
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const selectedId = searchParams.get('selected') ?? undefined
  const sourcePath = safeInternalPath(searchParams.get('from'))
  const [dialog, setDialog] = useState<DialogKind>()
  const [issuedPortalUrl, setIssuedPortalUrl] = useState<string>()
  const canWrite = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter'].includes(role),
  ) ?? false
  const isAdministrator = auth.user?.roles.includes('administrator') ?? false

  function selectOnboarding(onboardingId: string) {
    const next = new URLSearchParams(searchParams)
    next.set('selected', onboardingId)
    setSearchParams(next, { replace: true })
  }

  function closeOnboarding() {
    const next = new URLSearchParams(searchParams)
    next.delete('selected')
    setSearchParams(next, { replace: true })
    setIssuedPortalUrl(undefined)
  }

  const onboardings = useQuery({
    queryKey: ['onboardings'],
    queryFn: () => fetchOnboardings(),
  })
  const detail = useQuery({
    queryKey: ['onboarding', selectedId],
    queryFn: () => fetchOnboarding(selectedId!),
    enabled: Boolean(selectedId),
  })
  const portalLinks = useQuery({
    queryKey: ['offer-portal-links', detail.data?.offer_id],
    queryFn: () => fetchOfferPortalLinks(detail.data!.offer_id),
    enabled: Boolean(detail.data?.offer_id) && canWrite,
  })

  const visibleItems = useMemo(
    () => (onboardings.data?.items ?? []).filter((item) => belongsToFilter(item.status, statusFilter)),
    [onboardings.data, statusFilter],
  )
  const counts = useMemo(() => {
    const items = onboardings.data?.items ?? []
    return {
      all: items.length,
      pending_confirmation: items.filter((item) => belongsToFilter(item.status, 'pending_confirmation')).length,
      pending_start: items.filter((item) => item.status === 'pending_start').length,
      onboarded: items.filter((item) => item.status === 'onboarded').length,
      abandoned: items.filter((item) => item.status === 'abandoned').length,
    }
  }, [onboardings.data])

  function updateDetail(saved: OnboardingDetailRecord, successMessage: string) {
    queryClient.setQueryData(['onboarding', saved.id], saved)
    void queryClient.invalidateQueries({ queryKey: ['onboardings'] })
    setDialog(undefined)
    form.resetFields()
    void messageApi.success(successMessage)
  }

  const acceptDate = useMutation({
    mutationFn: (record: OnboardingDetailRecord) =>
      decideOnboardingDate(record.id, record.version, 'accept', null, '同意候选人提议日期'),
    onSuccess: (saved) => updateDetail(saved, '已确认候选人入职日期'),
  })

  const actionMutation = useMutation({
    mutationFn: async ({
      kind,
      values,
      record,
    }: {
      kind: Exclude<DialogKind, 'regenerate-link'>
      values: ActionValues
      record: OnboardingDetailRecord
    }) => {
      if (kind === 'propose') {
        return decideOnboardingDate(
          record.id,
          record.version,
          'propose',
          values.date!,
          values.note?.trim() || null,
        )
      }
      if (kind === 'onboard') {
        return markOnboardingCompleted(
          record.id,
          record.version,
          values.date!,
          values.note?.trim() || null,
        )
      }
      if (kind === 'abandon') {
        return abandonOnboarding(
          record.id,
          record.version,
          values.source!,
          values.reasonCode!,
          values.note!.trim(),
        )
      }
      return correctOnboardingStatus(record.id, record.version, values.note!.trim())
    },
    onSuccess: (saved, variables) => {
      const labels = {
        propose: '已提出新的入职日期',
        onboard: '已标记候选人入职',
        abandon: '已记录放弃入职',
        correct: '已追加状态更正',
      }
      updateDetail(saved, labels[variables.kind])
    },
  })

  const linkMutation = useMutation({
    mutationFn: async ({ record, reason }: { record: OnboardingDetailRecord; reason?: string }) => {
      const hasUnrevokedLink = (portalLinks.data ?? []).some((link) => link.state !== 'revoked')
      return hasUnrevokedLink
        ? regenerateOnboardingPortalLink(record.id, reason!)
        : createOnboardingPortalLink(record.id)
    },
    onSuccess: (issued) => {
      void queryClient.invalidateQueries({ queryKey: ['offer-portal-links', detail.data?.offer_id] })
      setDialog(undefined)
      form.resetFields()
      if (issued.portal_token) {
        setIssuedPortalUrl(`${window.location.origin}/offer#${issued.portal_token}`)
      }
      void messageApi.success('新的入职访问链接已生成')
    },
  })

  const columns: ColumnsType<OnboardingSummaryRecord> = [
    {
      title: '候选人',
      key: 'candidate',
      width: 210,
      render: (_, item) => (
        <div className="onboarding-candidate-cell">
          <Text strong>{item.candidate_name || item.candidate_code}</Text>
          <Text type="secondary">{item.candidate_phone ?? '联系方式受限'}</Text>
        </div>
      ),
    },
    { title: '岗位', dataIndex: 'job_title', key: 'job', width: 220 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 150,
      render: (status: OnboardingStatus) => (
        <Tag color={statusMeta[status].color}>{statusMeta[status].label}</Tag>
      ),
    },
    {
      title: '当前责任方',
      dataIndex: 'action_owner',
      key: 'owner',
      width: 130,
      render: (owner: OnboardingSummaryRecord['action_owner']) =>
        owner === 'candidate' ? '候选人' : owner === 'recruiter' ? '招聘专员' : '无需操作',
    },
    {
      title: '当前日期',
      key: 'date',
      width: 150,
      render: (_, item) => formatDate(currentDate(item)),
    },
    {
      title: '最近更新',
      dataIndex: 'updated_at',
      key: 'updated',
      width: 180,
      render: formatDateTime,
    },
  ]

  const current = detail.data
  const hasUnrevokedLink = (portalLinks.data ?? []).some((link) => link.state !== 'revoked')
  const actionError = acceptDate.error ?? actionMutation.error ?? linkMutation.error

  function openDialog(kind: DialogKind) {
    if (!current) return
    setIssuedPortalUrl(undefined)
    form.resetFields()
    if (kind === 'propose') {
      form.setFieldsValue({
        date: current.candidate_proposed_date ?? current.confirmed_start_date ?? current.expected_start_date,
      })
    } else if (kind === 'onboard') {
      form.setFieldsValue({ date: today() })
    } else if (kind === 'abandon') {
      form.setFieldsValue({ source: 'candidate_withdrew', reasonCode: 'personal' })
    }
    setDialog(kind)
  }

  async function submitDialog() {
    if (!dialog || !current) return
    const values = await form.validateFields()
    if (dialog === 'regenerate-link') {
      linkMutation.mutate({ record: current, reason: values.note?.trim() })
      return
    }
    actionMutation.mutate({ kind: dialog, values, record: current })
  }

  return (
    <>
      {messageContext}
      {modalContext}
      <div className="page-heading">
        <div>
          <Title level={2}>入职跟踪</Title>
          <Text type="secondary">协调候选人入职日期并记录最终入职结果</Text>
        </div>
        <Space wrap>
          {sourcePath && sourcePath !== `${location.pathname}${location.search}` && (
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(sourcePath)}>
              {returnLabel(sourcePath)}
            </Button>
          )}
          <Button
            icon={<ReloadOutlined />}
            loading={onboardings.isFetching}
            onClick={() => void onboardings.refetch()}
          >
            刷新
          </Button>
        </Space>
      </div>

      <HiringModuleNav />

      {onboardings.error && (
        <Alert
          className="page-alert"
          type="error"
          showIcon
          message="无法读取入职记录"
          description={onboardings.error instanceof ApiError ? onboardings.error.message : '请稍后重试'}
        />
      )}

      <section className="onboarding-workspace">
        <div className="onboarding-filter-bar">
          <Segmented<StatusFilter>
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { label: `全部 ${counts.all}`, value: 'all' },
              { label: `待确认 ${counts.pending_confirmation}`, value: 'pending_confirmation' },
              { label: `待入职 ${counts.pending_start}`, value: 'pending_start' },
              { label: `已入职 ${counts.onboarded}`, value: 'onboarded' },
              { label: `已放弃 ${counts.abandoned}`, value: 'abandoned' },
            ]}
          />
        </div>
        <Table<OnboardingSummaryRecord>
          rowKey="id"
          columns={columns}
          dataSource={visibleItems}
          loading={onboardings.isPending}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无入职记录" /> }}
          rowClassName={(item) => item.id === selectedId ? 'onboarding-row-selected' : ''}
          onRow={(item) => ({ onClick: () => selectOnboarding(item.id) })}
          scroll={{ x: 1040 }}
        />
      </section>

      <Drawer
        width={720}
        title={current ? `${current.candidate_name || current.candidate_code} · 入职详情` : '入职详情'}
        open={Boolean(selectedId)}
        onClose={closeOnboarding}
      >
        {detail.isPending && <Skeleton active paragraph={{ rows: 12 }} />}
        {detail.error && (
          <Alert
            type="error"
            showIcon
            message="无法读取入职详情"
            description={detail.error instanceof Error ? detail.error.message : '请稍后重试'}
          />
        )}
        {current && (
          <div className="onboarding-detail">
            <Space wrap className="onboarding-detail-actions">
              {canWrite && current.status === 'candidate_proposed_date' && (
                <Button
                  type="primary"
                  icon={<CheckOutlined />}
                  loading={acceptDate.isPending}
                  onClick={() => {
                    modal.confirm({
                      title: '确认候选人提出的入职日期？',
                      content: formatDate(current.candidate_proposed_date),
                      okText: '确认日期',
                      cancelText: '返回',
                      onOk: () => acceptDate.mutateAsync(current),
                    })
                  }}
                >
                  接受候选人日期
                </Button>
              )}
              {canWrite && ['pending_confirmation', 'candidate_proposed_date', 'pending_start'].includes(current.status) && (
                <Button icon={<EditOutlined />} onClick={() => openDialog('propose')}>
                  提出新日期
                </Button>
              )}
              {canWrite && current.status === 'pending_start' && (
                <Button type="primary" icon={<CheckOutlined />} onClick={() => openDialog('onboard')}>
                  标记已入职
                </Button>
              )}
              {canWrite && ['pending_confirmation', 'candidate_proposed_date', 'pending_start'].includes(current.status) && (
                <Button danger icon={<StopOutlined />} onClick={() => openDialog('abandon')}>
                  标记放弃
                </Button>
              )}
              {isAdministrator && current.status === 'onboarded' && (
                <Button icon={<SyncOutlined />} onClick={() => openDialog('correct')}>
                  更正误标
                </Button>
              )}
            </Space>

            {actionError && (
              <Alert
                type="error"
                showIcon
                message="操作未完成"
                description={actionError instanceof Error ? actionError.message : '请稍后重试'}
              />
            )}

            <Descriptions bordered column={{ xs: 1, sm: 2 }} size="small" title="当前状态">
              <Descriptions.Item label="状态">
                <Tag color={statusMeta[current.status].color}>{statusMeta[current.status].label}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="责任方">
                {current.action_owner === 'candidate' ? '候选人' : current.action_owner === 'recruiter' ? '招聘专员' : '无需操作'}
              </Descriptions.Item>
              <Descriptions.Item label="岗位">{current.job_title}</Descriptions.Item>
              <Descriptions.Item label="电话">{current.candidate_phone ?? '无权限查看'}</Descriptions.Item>
              <Descriptions.Item label="Offer 预计日期">{formatDate(current.expected_start_date)}</Descriptions.Item>
              <Descriptions.Item label="候选人提议">{formatDate(current.candidate_proposed_date)}</Descriptions.Item>
              <Descriptions.Item label="招聘方提议">{formatDate(current.recruiter_proposed_date)}</Descriptions.Item>
              <Descriptions.Item label="确认日期">{formatDate(current.confirmed_start_date)}</Descriptions.Item>
              <Descriptions.Item label="实际入职日期">{formatDate(current.actual_start_date)}</Descriptions.Item>
              <Descriptions.Item label="当前版本">V{current.version}</Descriptions.Item>
              {current.status === 'abandoned' && (
                <>
                  <Descriptions.Item label="放弃来源">
                    {sourceLabels[current.abandonment_source!]}
                  </Descriptions.Item>
                  <Descriptions.Item label="原因分类">
                    {reasonLabels[current.abandonment_reason_code!]}
                  </Descriptions.Item>
                  <Descriptions.Item label="说明" span={{ xs: 1, sm: 2 }}>
                    {current.abandonment_note}
                  </Descriptions.Item>
                </>
              )}
            </Descriptions>

            {canWrite && (
              <section className="onboarding-link-section">
                <div>
                  <Title level={4}>候选人访问</Title>
                  <Text type="secondary">链接只在生成时返回一次，候选人仍需验证手机号后四位。</Text>
                </div>
                <Button
                  icon={<LinkOutlined />}
                  loading={portalLinks.isPending || linkMutation.isPending}
                  onClick={() => {
                    if (hasUnrevokedLink) openDialog('regenerate-link')
                    else linkMutation.mutate({ record: current })
                  }}
                >
                  {hasUnrevokedLink ? '重新生成链接' : '生成入职链接'}
                </Button>
              </section>
            )}

            {issuedPortalUrl && (
              <Alert
                type="success"
                showIcon
                message="新链接已生成，请立即复制"
                description={
                  <Space.Compact block>
                    <Input value={issuedPortalUrl} readOnly />
                    <Button
                      icon={<CopyOutlined />}
                      onClick={async () => {
                        await navigator.clipboard.writeText(issuedPortalUrl)
                        void messageApi.success('链接已复制')
                      }}
                    >
                      复制
                    </Button>
                  </Space.Compact>
                }
              />
            )}

            <div className="onboarding-timeline">
              <Title level={4}>状态记录</Title>
              <Timeline
                items={[...current.events].reverse().map((event) => ({
                  color: event.to_status === 'abandoned' ? 'gray' : event.to_status === 'onboarded' ? 'green' : 'blue',
                  children: (
                    <div className="onboarding-event">
                      <Space wrap>
                        <Text strong>{eventLabels[event.action]}</Text>
                        <Tag>{statusMeta[event.to_status].label}</Tag>
                      </Space>
                      <Text type="secondary">
                        {formatDateTime(event.created_at)} · {event.actor_display_name || (event.actor_type === 'candidate' ? '候选人' : '系统')}
                      </Text>
                      {event.date_after && <Text>日期：{formatDate(event.date_after)}</Text>}
                      {event.reason && <Text>说明：{event.reason}</Text>}
                    </div>
                  ),
                }))}
              />
            </div>
          </div>
        )}
      </Drawer>

      <Modal
        title={{
          propose: '提出新的入职日期',
          onboard: '标记候选人已入职',
          abandon: '记录放弃入职',
          correct: '更正误标的已入职状态',
          'regenerate-link': '重新生成入职访问链接',
        }[dialog ?? 'propose']}
        open={Boolean(dialog)}
        forceRender
        okText="确认"
        cancelText="返回"
        confirmLoading={actionMutation.isPending || linkMutation.isPending}
        onOk={() => void submitDialog()}
        onCancel={() => {
          setDialog(undefined)
          form.resetFields()
        }}
      >
        <Form<ActionValues> form={form} layout="vertical" requiredMark={false}>
          {dialog === 'propose' && (
            <>
              <Form.Item label="新入职日期" name="date" rules={[{ required: true, message: '请选择入职日期' }]}>
                <Input type="date" min={today()} />
              </Form.Item>
              <Form.Item label="调整说明" name="note" rules={[{ required: true, message: '请填写调整说明' }]}>
                <Input.TextArea rows={3} maxLength={2_000} showCount />
              </Form.Item>
            </>
          )}
          {dialog === 'onboard' && (
            <>
              <Form.Item label="实际入职日期" name="date" rules={[{ required: true, message: '请选择实际入职日期' }]}>
                <Input type="date" max={today()} />
              </Form.Item>
              <Form.Item label="说明" name="note">
                <Input.TextArea rows={3} maxLength={2_000} showCount />
              </Form.Item>
            </>
          )}
          {dialog === 'abandon' && (
            <>
              <Form.Item label="责任来源" name="source" rules={[{ required: true }]}>
                <Select options={Object.entries(sourceLabels).map(([value, label]) => ({ value, label }))} />
              </Form.Item>
              <Form.Item label="原因分类" name="reasonCode" rules={[{ required: true }]}>
                <Select options={Object.entries(reasonLabels).map(([value, label]) => ({ value, label }))} />
              </Form.Item>
              <Form.Item label="详细说明" name="note" rules={[{ required: true, message: '请填写说明' }]}>
                <Input.TextArea rows={3} maxLength={2_000} showCount />
              </Form.Item>
            </>
          )}
          {dialog === 'correct' && (
            <Form.Item label="更正原因" name="note" rules={[{ required: true, message: '请填写更正原因' }]}>
              <Input.TextArea rows={3} maxLength={2_000} showCount />
            </Form.Item>
          )}
          {dialog === 'regenerate-link' && (
            <Form.Item label="重新生成原因" name="note" rules={[{ required: true, message: '请填写原因' }]}>
              <Input.TextArea rows={3} maxLength={2_000} showCount />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </>
  )
}
