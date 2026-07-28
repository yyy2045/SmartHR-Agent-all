import {
  CheckOutlined,
  CopyOutlined,
  EditOutlined,
  EyeOutlined,
  LinkOutlined,
  ReloadOutlined,
  SendOutlined,
  StopOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Skeleton,
  Space,
  Table,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import {
  ApiError,
  createOffer,
  createOfferPortalLink,
  createOfferVersion,
  decideOfferAsApprover,
  decideOfferAsManager,
  fetchOffer,
  fetchOfferPortalLinks,
  fetchOffers,
  regenerateOfferPortalLink,
  revokeOfferPortalLink,
  submitOffer,
  type OfferContentInput,
  type OfferPortalLinkIssuedRecord,
  type OfferPortalLinkRecord,
  type OfferPortalLinkState,
  type OfferRecord,
  type OfferStatus,
  type OfferSummary,
  type OfferVersion,
} from '../api/client'
import { useAuth } from '../auth/context'
import { HiringModuleNav } from '../components/HiringModuleNav'

const { Title, Text, Paragraph } = Typography

const statusMeta: Record<OfferStatus, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  pending_manager_confirmation: { label: '待经理确认', color: 'processing' },
  pending_approval: { label: '待最终审批', color: 'warning' },
  approved: { label: '已批准', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
  pending_response: { label: '待候选人回应', color: 'processing' },
  accepted: { label: '候选人已接受', color: 'success' },
  declined: { label: '候选人已拒绝', color: 'error' },
}

type StatusFilter = 'all' | OfferStatus
type DecisionTarget =
  | { kind: 'manager'; decision: 'confirmed' | 'rejected' }
  | { kind: 'approver'; decision: 'approved' | 'rejected' }

type OfferFormValues = OfferContentInput

interface DecisionFormValues {
  comment: string
}

interface PortalLinkReasonValues {
  reason: string
}

type PortalLinkAction =
  | { kind: 'regenerate'; link: OfferPortalLinkRecord }
  | { kind: 'revoke'; link: OfferPortalLinkRecord }

interface CreateTarget {
  jobId: string
  applicationId: string
}

function formatDate(value: string) {
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

function dateAfter(days: number) {
  const value = new Date()
  value.setDate(value.getDate() + days)
  return value.toISOString().slice(0, 10)
}

function money(value: string | number | null) {
  if (value === null) return '不适用'
  return `${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 元/月`
}

function annualSalary(version: OfferVersion) {
  const total = Number(version.monthly_salary) * Number(version.annual_salary_months)
  return `${total.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 元/年`
}

function offerFormValues(version: OfferVersion): OfferFormValues {
  return {
    monthly_salary: Number(version.monthly_salary),
    annual_salary_months: Number(version.annual_salary_months),
    probation_months: version.probation_months,
    probation_monthly_salary:
      version.probation_monthly_salary === null
        ? null
        : Number(version.probation_monthly_salary),
    bonus_description: version.bonus_description,
    expected_start_date: version.expected_start_date,
    valid_until: version.valid_until,
    notes: version.notes,
  }
}

function versionSummary(version: OfferVersion) {
  return `${money(version.monthly_salary)} × ${Number(version.annual_salary_months)} 薪`
}

const portalLinkStateMeta: Record<OfferPortalLinkState, { label: string; color: string }> = {
  active: { label: '有效', color: 'processing' },
  expired: { label: '已过期', color: 'default' },
  revoked: { label: '已撤回', color: 'warning' },
  responded: { label: '已回应', color: 'success' },
}

export function OfferManagementPage() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [messageApi, messageContext] = message.useMessage()
  const [modal, modalContext] = Modal.useModal()
  const [offerForm] = Form.useForm<OfferFormValues>()
  const [decisionForm] = Form.useForm<DecisionFormValues>()
  const [portalLinkReasonForm] = Form.useForm<PortalLinkReasonValues>()
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [selectedId, setSelectedId] = useState<string>()
  const [formOpen, setFormOpen] = useState(false)
  const [editingOffer, setEditingOffer] = useState<OfferRecord>()
  const [createTarget, setCreateTarget] = useState<CreateTarget>()
  const [decisionTarget, setDecisionTarget] = useState<DecisionTarget>()
  const [portalLinkAction, setPortalLinkAction] = useState<PortalLinkAction>()
  const [issuedPortalUrl, setIssuedPortalUrl] = useState<string>()
  const [versionKey, setVersionKey] = useState(() => crypto.randomUUID())
  const canWrite = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter'].includes(role),
  ) ?? false
  const canManager = auth.user?.roles.some((role) =>
    ['administrator', 'hiring_manager'].includes(role),
  ) ?? false
  const canApprove = auth.user?.roles.some((role) =>
    ['administrator', 'approver'].includes(role),
  ) ?? false

  const offers = useQuery({
    queryKey: ['offers'],
    queryFn: () => fetchOffers(),
  })
  const detail = useQuery({
    queryKey: ['offer', selectedId],
    queryFn: () => fetchOffer(selectedId!),
    enabled: Boolean(selectedId),
  })
  const portalLinks = useQuery({
    queryKey: ['offer-portal-links', selectedId],
    queryFn: () => fetchOfferPortalLinks(selectedId!),
    enabled: Boolean(selectedId),
  })
  const visibleOffers = useMemo(
    () =>
      (offers.data ?? []).filter(
        (offer) => statusFilter === 'all' || offer.status === statusFilter,
      ),
    [offers.data, statusFilter],
  )
  const counts = useMemo(() => {
    const values = Object.fromEntries(
      Object.keys(statusMeta).map((offerStatus) => [offerStatus, 0]),
    ) as Record<OfferStatus, number>
    for (const offer of offers.data ?? []) values[offer.status] += 1
    return values
  }, [offers.data])

  useEffect(() => {
    if (!canWrite || searchParams.get('create') !== '1') return
    const jobId = searchParams.get('jobId')
    const applicationId = searchParams.get('applicationId')
    if (!jobId || !applicationId) return
    setCreateTarget({ jobId, applicationId })
    setEditingOffer(undefined)
    setVersionKey(crypto.randomUUID())
    offerForm.setFieldsValue({
      monthly_salary: 30_000,
      annual_salary_months: 12,
      probation_months: 3,
      probation_monthly_salary: 30_000,
      bonus_description: '',
      valid_until: dateAfter(7),
      expected_start_date: dateAfter(30),
      notes: '',
    })
    setFormOpen(true)
    setSearchParams({}, { replace: true })
  }, [canWrite, offerForm, searchParams, setSearchParams])

  useEffect(() => {
    setIssuedPortalUrl(undefined)
    setPortalLinkAction(undefined)
  }, [selectedId])

  function updateOfferCache(saved: OfferRecord) {
    queryClient.setQueryData(['offer', saved.id], saved)
    queryClient.setQueryData<OfferSummary[]>(['offers'], (current = []) => {
      const summary: OfferSummary = saved
      return current.some((item) => item.id === saved.id)
        ? current.map((item) => (item.id === saved.id ? summary : item))
        : [summary, ...current]
    })
    void queryClient.invalidateQueries({ queryKey: ['offers'] })
  }

  const saveMutation = useMutation({
    mutationFn: (values: OfferFormValues) => {
      if (values.valid_until >= values.expected_start_date) {
        throw new Error('预计入职日必须晚于 Offer 有效期')
      }
      const content: OfferContentInput = {
        ...values,
        probation_monthly_salary:
          values.probation_months === 0 ? null : values.probation_monthly_salary,
        bonus_description: values.bonus_description ?? '',
        notes: values.notes ?? '',
      }
      if (editingOffer) {
        return createOfferVersion(
          editingOffer.id,
          versionKey,
          editingOffer.current_version.id,
          content,
        )
      }
      if (!createTarget) throw new Error('缺少职位应聘记录')
      return createOffer(
        createTarget.jobId,
        createTarget.applicationId,
        versionKey,
        content,
      )
    },
    onSuccess: (saved) => {
      updateOfferCache(saved)
      setSelectedId(saved.id)
      setFormOpen(false)
      setEditingOffer(undefined)
      setCreateTarget(undefined)
      void messageApi.success(
        saved.current_version_number === 1 ? 'Offer 草稿已创建' : 'Offer 新版本已保存',
      )
    },
    onError: (error) =>
      void messageApi.error(error instanceof Error ? error.message : '保存 Offer 失败'),
  })
  const submitMutation = useMutation({
    mutationFn: (offer: OfferRecord) =>
      submitOffer(offer.id, offer.current_version.id),
    onSuccess: (saved) => {
      updateOfferCache(saved)
      void messageApi.success('Offer 已提交用人经理确认')
    },
    onError: (error) =>
      void messageApi.error(error instanceof Error ? error.message : '提交 Offer 失败'),
  })
  const decisionMutation = useMutation({
    mutationFn: ({
      offer,
      target,
      comment,
    }: {
      offer: OfferRecord
      target: DecisionTarget
      comment: string
    }) => {
      if (target.kind === 'manager') {
        return decideOfferAsManager(
          offer.id,
          offer.current_version.id,
          target.decision,
          comment,
        )
      }
      return decideOfferAsApprover(
        offer.id,
        offer.current_version.id,
        target.decision,
        comment,
      )
    },
    onSuccess: (saved, variables) => {
      updateOfferCache(saved)
      setDecisionTarget(undefined)
      decisionForm.resetFields()
      const label =
        variables.target.decision === 'confirmed'
          ? '录用已确认'
          : variables.target.decision === 'approved'
            ? 'Offer 已批准'
            : 'Offer 已驳回'
      void messageApi.success(label)
    },
    onError: (error) =>
      void messageApi.error(error instanceof Error ? error.message : '处理 Offer 失败'),
  })

  function refreshPortalState() {
    void queryClient.invalidateQueries({ queryKey: ['offer-portal-links', selectedId] })
    void queryClient.invalidateQueries({ queryKey: ['offer', selectedId] })
    void queryClient.invalidateQueries({ queryKey: ['offers'] })
  }

  function rememberIssuedPortalLink(link: OfferPortalLinkIssuedRecord) {
    if (!link.portal_token) {
      void messageApi.warning('本次操作已处理，但原始链接不可再次读取，请重新生成')
      return
    }
    setIssuedPortalUrl(`${window.location.origin}/offer#${link.portal_token}`)
  }

  const createPortalLinkMutation = useMutation({
    mutationFn: (offerId: string) => createOfferPortalLink(offerId),
    onSuccess: (link) => {
      rememberIssuedPortalLink(link)
      refreshPortalState()
      void messageApi.success('候选人链接已生成')
    },
    onError: (error) =>
      void messageApi.error(error instanceof Error ? error.message : '生成候选人链接失败'),
  })
  const regeneratePortalLinkMutation = useMutation({
    mutationFn: ({ offerId, reason }: { offerId: string; reason: string }) =>
      regenerateOfferPortalLink(offerId, reason),
    onSuccess: (link) => {
      rememberIssuedPortalLink(link)
      setPortalLinkAction(undefined)
      portalLinkReasonForm.resetFields()
      refreshPortalState()
      void messageApi.success('候选人链接已重新生成，旧链接已失效')
    },
    onError: (error) =>
      void messageApi.error(error instanceof Error ? error.message : '重新生成链接失败'),
  })
  const revokePortalLinkMutation = useMutation({
    mutationFn: ({ offerId, linkId, reason }: { offerId: string; linkId: string; reason: string }) =>
      revokeOfferPortalLink(offerId, linkId, reason),
    onSuccess: () => {
      setIssuedPortalUrl(undefined)
      setPortalLinkAction(undefined)
      portalLinkReasonForm.resetFields()
      refreshPortalState()
      void messageApi.success('候选人链接已撤回')
    },
    onError: (error) =>
      void messageApi.error(error instanceof Error ? error.message : '撤回候选人链接失败'),
  })

  async function copyIssuedPortalLink() {
    if (!issuedPortalUrl) return
    try {
      if (!navigator.clipboard) throw new Error('当前浏览器不支持剪贴板')
      await navigator.clipboard.writeText(issuedPortalUrl)
      setIssuedPortalUrl(undefined)
      void messageApi.success('候选人链接已复制，本页不再保留原始链接')
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '复制候选人链接失败')
    }
  }

  function submitPortalLinkAction() {
    if (!detail.data || !portalLinkAction) return
    void portalLinkReasonForm.validateFields().then(({ reason }) => {
      if (portalLinkAction.kind === 'regenerate') {
        regeneratePortalLinkMutation.mutate({ offerId: detail.data!.id, reason })
        return
      }
      revokePortalLinkMutation.mutate({
        offerId: detail.data!.id,
        linkId: portalLinkAction.link.id,
        reason,
      })
    })
  }

  function openRevision(offer: OfferRecord) {
    setEditingOffer(offer)
    setCreateTarget(undefined)
    setVersionKey(crypto.randomUUID())
    offerForm.setFieldsValue(offerFormValues(offer.current_version))
    setFormOpen(true)
  }

  function closeForm() {
    setFormOpen(false)
    setEditingOffer(undefined)
    setCreateTarget(undefined)
    offerForm.resetFields()
  }

  function submitDecision() {
    if (!detail.data || !decisionTarget) return
    void decisionForm.validateFields().then((values) => {
      decisionMutation.mutate({
        offer: detail.data!,
        target: decisionTarget,
        comment: values.comment ?? '',
      })
    })
  }

  const columns: ColumnsType<OfferSummary> = [
    {
      title: '候选人',
      key: 'candidate',
      render: (_, offer) => (
        <div className="offer-identity-cell">
          <Text strong>{offer.candidate_name || offer.candidate_code}</Text>
          <Text type="secondary">{offer.candidate_code}</Text>
        </div>
      ),
    },
    { title: '岗位', dataIndex: 'job_title', key: 'job', ellipsis: true },
    {
      title: '薪酬方案',
      key: 'salary',
      render: (_, offer) => versionSummary(offer.current_version),
    },
    {
      title: '版本',
      key: 'version',
      width: 80,
      render: (_, offer) => `V${offer.current_version_number}`,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 130,
      render: (value: OfferStatus) => (
        <Tag color={statusMeta[value].color}>{statusMeta[value].label}</Tag>
      ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: formatDateTime,
    },
    {
      title: '',
      key: 'action',
      width: 56,
      render: (_, offer) => (
        <Button
          type="text"
          aria-label={`查看 ${offer.candidate_name || offer.candidate_code} 的 Offer`}
          icon={<EyeOutlined />}
          onClick={(event) => {
            event.stopPropagation()
            setSelectedId(offer.id)
          }}
        />
      ),
    },
  ]

  const listContent = (
    <>
      {offers.error && (
        <Alert
          className="page-alert"
          type="error"
          showIcon
          message="无法读取 Offer 列表"
          description={
            offers.error instanceof ApiError ? offers.error.message : '请稍后重试'
          }
        />
      )}
      <section className="offer-workspace">
        <div className="offer-filter-bar">
          <Segmented<StatusFilter>
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { label: `全部 ${offers.data?.length ?? 0}`, value: 'all' },
              ...Object.entries(statusMeta).map(([value, meta]) => ({
                label: `${meta.label} ${counts[value as OfferStatus]}`,
                value: value as OfferStatus,
              })),
            ]}
          />
        </div>
        <Table<OfferSummary>
          rowKey="id"
          columns={columns}
          dataSource={visibleOffers}
          loading={offers.isPending}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无 Offer" /> }}
          rowClassName={(offer) =>
            offer.id === selectedId ? 'offer-row-selected' : ''
          }
          onRow={(offer) => ({ onClick: () => setSelectedId(offer.id) })}
          scroll={{ x: 920 }}
        />
      </section>
    </>
  )

  return (
    <>
      {messageContext}
      {modalContext}
      <div className="page-heading">
        <div>
          <Title level={2}>录用管理</Title>
          <Text type="secondary">集中处理薪酬方案、经理确认和最终审批</Text>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={offers.isFetching}
          onClick={() => void offers.refetch()}
        >
          刷新
        </Button>
      </div>

      <HiringModuleNav />
      {listContent}

      <Drawer
        width={680}
        title={detail.data ? `${detail.data.candidate_name || detail.data.candidate_code} · Offer` : 'Offer 详情'}
        open={Boolean(selectedId)}
        onClose={() => setSelectedId(undefined)}
      >
        {detail.isPending && <Skeleton active paragraph={{ rows: 12 }} />}
        {detail.error && (
          <Alert
            type="error"
            showIcon
            message="无法读取 Offer 详情"
            description={detail.error instanceof Error ? detail.error.message : '请稍后重试'}
          />
        )}
        {detail.data && (
          <div className="offer-detail">
            <Space wrap className="offer-detail-actions">
              {canWrite && ['draft', 'rejected'].includes(detail.data.status) && (
                <Button icon={<EditOutlined />} onClick={() => openRevision(detail.data!)}>
                  {detail.data.status === 'rejected' ? '创建修订版本' : '修改薪酬方案'}
                </Button>
              )}
              {canWrite && detail.data.status === 'draft' && (
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  aria-label="提交确认"
                  loading={submitMutation.isPending}
                  onClick={() => {
                    modal.confirm({
                      title: '提交用人经理确认？',
                      content: '提交后当前薪酬版本将锁定，不能直接修改。',
                      okText: '提交',
                      cancelText: '取消',
                      onOk: () => submitMutation.mutateAsync(detail.data!),
                    })
                  }}
                >
                  提交确认
                </Button>
              )}
              {canManager && detail.data.status === 'pending_manager_confirmation' && (
                <>
                  <Button
                    type="primary"
                    icon={<CheckOutlined />}
                    aria-label="确认录用"
                    onClick={() => setDecisionTarget({ kind: 'manager', decision: 'confirmed' })}
                  >
                    确认录用
                  </Button>
                  <Button
                    danger
                    icon={<StopOutlined />}
                    onClick={() => setDecisionTarget({ kind: 'manager', decision: 'rejected' })}
                  >
                    驳回
                  </Button>
                </>
              )}
              {canApprove && detail.data.status === 'pending_approval' && (
                <>
                  <Button
                    type="primary"
                    icon={<CheckOutlined />}
                    aria-label="批准 Offer"
                    onClick={() => setDecisionTarget({ kind: 'approver', decision: 'approved' })}
                  >
                    批准 Offer
                  </Button>
                  <Button
                    danger
                    icon={<StopOutlined />}
                    onClick={() => setDecisionTarget({ kind: 'approver', decision: 'rejected' })}
                  >
                    驳回
                  </Button>
                </>
              )}
            </Space>

            <Descriptions bordered column={2} size="small" title="当前薪酬方案">
              <Descriptions.Item label="状态">
                <Tag color={statusMeta[detail.data.status].color}>
                  {statusMeta[detail.data.status].label}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="当前版本">
                V{detail.data.current_version_number}
              </Descriptions.Item>
              <Descriptions.Item label="月薪">
                {money(detail.data.current_version.monthly_salary)}
              </Descriptions.Item>
              <Descriptions.Item label="年薪月数">
                {Number(detail.data.current_version.annual_salary_months)} 薪
              </Descriptions.Item>
              <Descriptions.Item label="参考年薪" span={2}>
                {annualSalary(detail.data.current_version)}
              </Descriptions.Item>
              <Descriptions.Item label="试用期">
                {detail.data.current_version.probation_months
                  ? `${detail.data.current_version.probation_months} 个月`
                  : '无'}
              </Descriptions.Item>
              <Descriptions.Item label="试用期月薪">
                {money(detail.data.current_version.probation_monthly_salary)}
              </Descriptions.Item>
              <Descriptions.Item label="Offer 有效期">
                {formatDate(detail.data.current_version.valid_until)}
              </Descriptions.Item>
              <Descriptions.Item label="预计入职日">
                {formatDate(detail.data.current_version.expected_start_date)}
              </Descriptions.Item>
              <Descriptions.Item label="奖金说明" span={2}>
                {detail.data.current_version.bonus_description || '未填写'}
              </Descriptions.Item>
              <Descriptions.Item label="备注" span={2}>
                {detail.data.current_version.notes || '未填写'}
              </Descriptions.Item>
            </Descriptions>

            <Divider />
            <div className="offer-portal-section">
              <div className="offer-section-heading">
                <div>
                  <Title level={4}>候选人门户</Title>
                  <Text type="secondary">
                    链接只在生成时返回一次，候选人需使用手机号后四位验证。
                  </Text>
                </div>
                {canWrite &&
                  detail.data.status === 'approved' &&
                  !(portalLinks.data ?? []).some((link) => link.state === 'active') && (
                    <Button
                      type="primary"
                      icon={<LinkOutlined />}
                      loading={createPortalLinkMutation.isPending}
                      onClick={() => createPortalLinkMutation.mutate(detail.data!.id)}
                    >
                      生成候选人链接
                    </Button>
                  )}
              </div>

              {issuedPortalUrl && (
                <Alert
                  type="warning"
                  showIcon
                  message="请立即复制并通过外部工具发送"
                  description={
                    <div className="offer-portal-issued">
                      <Input
                        value={issuedPortalUrl}
                        readOnly
                        aria-label="新生成的候选人链接"
                      />
                      <Button
                        type="primary"
                        icon={<CopyOutlined />}
                        onClick={() => void copyIssuedPortalLink()}
                      >
                        复制链接
                      </Button>
                    </div>
                  }
                />
              )}

              {portalLinks.isPending && <Skeleton active paragraph={{ rows: 3 }} />}
              {portalLinks.error && (
                <Alert
                  type="error"
                  showIcon
                  message="无法读取候选人链接记录"
                  description={
                    portalLinks.error instanceof Error
                      ? portalLinks.error.message
                      : '请稍后重试'
                  }
                />
              )}
              {!portalLinks.isPending && !portalLinks.error && !portalLinks.data?.length && (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="尚未生成候选人链接"
                />
              )}
              {Boolean(portalLinks.data?.length) && (
                <div className="offer-portal-history">
                  {(portalLinks.data ?? []).map((link, index) => (
                    <div className="offer-portal-history-item" key={link.id}>
                      <div>
                        <Space wrap>
                          <Text strong>链接记录 {portalLinks.data!.length - index}</Text>
                          <Tag color={portalLinkStateMeta[link.state].color}>
                            {portalLinkStateMeta[link.state].label}
                          </Tag>
                          <Text type="secondary">
                            V
                            {detail.data!.versions.find(
                              (version) => version.id === link.version_id,
                            )?.version_number ?? '-'}
                          </Text>
                        </Space>
                        <div className="offer-portal-history-meta">
                          <Text type="secondary">
                            创建：{formatDateTime(link.created_at)} ·{' '}
                            {link.created_by_display_name}
                          </Text>
                          <Text type="secondary">
                            失效：{formatDateTime(link.expires_at)}
                          </Text>
                          {link.revoked_at && (
                            <Text type="secondary">
                              撤回：{formatDateTime(link.revoked_at)} ·{' '}
                              {link.revoked_by_display_name || link.revoked_by_username}
                            </Text>
                          )}
                          {link.revocation_reason && <Text>原因：{link.revocation_reason}</Text>}
                        </div>
                      </div>
                      {canWrite && link.state === 'active' && (
                        <Space wrap>
                          <Button
                            icon={<SyncOutlined />}
                            onClick={() =>
                              setPortalLinkAction({ kind: 'regenerate', link })
                            }
                          >
                            重新生成
                          </Button>
                          <Button
                            danger
                            icon={<StopOutlined />}
                            onClick={() => setPortalLinkAction({ kind: 'revoke', link })}
                          >
                            撤回链接
                          </Button>
                        </Space>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <Divider />
            <Title level={4}>版本与审批历史</Title>
            <Timeline
              items={[...detail.data.versions]
                .sort((left, right) => right.version_number - left.version_number)
                .map((version) => ({
                  color: version.approval?.decision === 'approved' ? 'green' : 'blue',
                  children: (
                    <div className="offer-version-item">
                      <Space wrap>
                        <Text strong>V{version.version_number}</Text>
                        <Text>{versionSummary(version)}</Text>
                        <Text type="secondary">{formatDateTime(version.created_at)}</Text>
                      </Space>
                      <Paragraph type="secondary">
                        {version.manager_confirmation
                          ? `经理：${version.manager_confirmation.confirmer_display_name} · ${version.manager_confirmation.decision === 'confirmed' ? '已确认' : '已驳回'}`
                          : '经理：待处理'}
                        {'；'}
                        {version.approval
                          ? `审批：${version.approval.approver_display_name} · ${version.approval.decision === 'approved' ? '已批准' : '已驳回'}`
                          : '审批：待处理'}
                      </Paragraph>
                      {version.manager_confirmation?.comment && (
                        <Text>经理意见：{version.manager_confirmation.comment}</Text>
                      )}
                      {version.approval?.comment && (
                        <Text>审批意见：{version.approval.comment}</Text>
                      )}
                    </div>
                  ),
                }))}
            />
          </div>
        )}
      </Drawer>

      <Modal
        title={editingOffer ? `修订 Offer V${editingOffer.current_version_number + 1}` : '创建 Offer 草稿'}
        open={formOpen}
        okText="保存草稿"
        cancelText="取消"
        width={720}
        confirmLoading={saveMutation.isPending}
        onCancel={closeForm}
        onOk={() => offerForm.submit()}
      >
        <Form<OfferFormValues>
          form={offerForm}
          layout="vertical"
          requiredMark="optional"
          onFinish={(values) => saveMutation.mutate(values)}
        >
          <div className="offer-form-grid">
            <Form.Item
              label="月薪（元）"
              name="monthly_salary"
              rules={[{ required: true, message: '请输入月薪' }]}
            >
              <InputNumber min={0.01} precision={2} step={1_000} />
            </Form.Item>
            <Form.Item
              label="年薪月数"
              name="annual_salary_months"
              rules={[{ required: true, message: '请输入年薪月数' }]}
            >
              <InputNumber min={1} max={36} precision={2} step={0.5} />
            </Form.Item>
            <Form.Item
              label="试用期（月）"
              name="probation_months"
              rules={[{ required: true, message: '请输入试用期' }]}
            >
              <InputNumber min={0} max={12} precision={0} />
            </Form.Item>
            <Form.Item
              noStyle
              shouldUpdate={(previous, current) =>
                previous.probation_months !== current.probation_months
              }
            >
              {({ getFieldValue }) => (
                <Form.Item
                  label="试用期月薪（元）"
                  name="probation_monthly_salary"
                  rules={
                    getFieldValue('probation_months') > 0
                      ? [{ required: true, message: '请输入试用期月薪' }]
                      : []
                  }
                >
                  <InputNumber
                    min={0.01}
                    precision={2}
                    step={1_000}
                    disabled={getFieldValue('probation_months') === 0}
                  />
                </Form.Item>
              )}
            </Form.Item>
            <Form.Item
              label="Offer 有效期"
              name="valid_until"
              rules={[{ required: true, message: '请选择 Offer 有效期' }]}
            >
              <Input type="date" />
            </Form.Item>
            <Form.Item
              label="预计入职日"
              name="expected_start_date"
              rules={[{ required: true, message: '请选择预计入职日' }]}
            >
              <Input type="date" />
            </Form.Item>
          </div>
          <Form.Item label="奖金说明" name="bonus_description">
            <Input.TextArea rows={3} maxLength={5_000} showCount />
          </Form.Item>
          <Form.Item label="备注" name="notes">
            <Input.TextArea rows={3} maxLength={5_000} showCount />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={
          portalLinkAction?.kind === 'regenerate'
            ? '重新生成候选人链接'
            : '撤回候选人链接'
        }
        open={Boolean(portalLinkAction)}
        okText={portalLinkAction?.kind === 'regenerate' ? '确认重新生成' : '确认撤回'}
        okButtonProps={{ danger: portalLinkAction?.kind === 'revoke' }}
        confirmLoading={
          regeneratePortalLinkMutation.isPending || revokePortalLinkMutation.isPending
        }
        onCancel={() => {
          setPortalLinkAction(undefined)
          portalLinkReasonForm.resetFields()
        }}
        onOk={submitPortalLinkAction}
      >
        <Alert
          type="warning"
          showIcon
          message={
            portalLinkAction?.kind === 'regenerate'
              ? '旧链接会立即失效，新链接仍只显示一次。'
              : '撤回后候选人将无法继续访问该链接。'
          }
        />
        <Form<PortalLinkReasonValues> form={portalLinkReasonForm} layout="vertical">
          <Form.Item
            label="操作原因"
            name="reason"
            rules={[{ required: true, whitespace: true, message: '请填写操作原因' }]}
          >
            <Input.TextArea rows={4} maxLength={2_000} showCount />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={
          decisionTarget?.decision === 'confirmed'
            ? '确认录用'
            : decisionTarget?.decision === 'approved'
              ? '批准 Offer'
              : '驳回 Offer'
        }
        open={Boolean(decisionTarget)}
        okText={decisionTarget?.decision === 'rejected' ? '确认驳回' : '确认'}
        okButtonProps={{ danger: decisionTarget?.decision === 'rejected' }}
        confirmLoading={decisionMutation.isPending}
        onCancel={() => {
          setDecisionTarget(undefined)
          decisionForm.resetFields()
        }}
        onOk={submitDecision}
      >
        <Form<DecisionFormValues> form={decisionForm} layout="vertical">
          <Form.Item
            label="处理意见"
            name="comment"
            rules={
              decisionTarget?.decision === 'rejected'
                ? [{ required: true, whitespace: true, message: '驳回时必须填写原因' }]
                : []
            }
          >
            <Input.TextArea rows={4} maxLength={5_000} showCount />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
