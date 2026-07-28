import {
  ApartmentOutlined,
  BranchesOutlined,
  EditOutlined,
  EyeOutlined,
  FileTextOutlined,
  MailOutlined,
  MergeCellsOutlined,
  PhoneOutlined,
  ReloadOutlined,
  SearchOutlined,
  StopOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Avatar,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Radio,
  Segmented,
  Skeleton,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  ApiError,
  dismissCandidateDuplicateReview,
  fetchCandidate,
  fetchCandidateDuplicateReviews,
  fetchCandidates,
  mergeCandidateDuplicateReview,
  updateCandidatePhone,
  type CandidateApplicationSummaryRecord,
  type CandidateDetailRecord,
  type CandidateDuplicateReviewRecord,
  type CandidateDuplicateReviewStatus,
  type CandidateListItemRecord,
  type CandidateListStatus,
  type CandidateResumeSummaryRecord,
  type CandidateStage,
  type CandidateSummaryRecord,
} from '../api/client'

const { Title, Text } = Typography
const PAGE_SIZE = 20

type CandidateCenterView = 'profiles' | 'duplicates'
type DuplicateStatusFilter = CandidateDuplicateReviewStatus | 'all'
type ResolutionAction =
  | { type: 'dismiss'; review: CandidateDuplicateReviewRecord }
  | { type: 'merge'; review: CandidateDuplicateReviewRecord }

interface PhoneUpdateValues {
  phone: string
  reason: string
}

const stageLabels: Record<CandidateStage, string> = {
  unprocessed: '待人工处理',
  pending: '待定',
  shortlisted: '初筛通过',
  to_contact: '待联系',
  contacted: '已联系',
  to_interview: '待面试',
  completed: '面试完成',
  offer_pending_response: 'Offer 待回应',
  offer_rejected: 'Offer 已拒绝',
  onboarding_pending_confirmation: '待确认入职',
  onboarding_pending_start: '待入职',
  onboarding_completed: '已入职',
  onboarding_abandoned: '已放弃入职',
  rejected: '已淘汰',
}

const signalLabels: Record<string, string> = {
  resume_sha256_exact: '简历文件一致',
  phone_exact: '手机号一致',
  email_exact: '邮箱一致',
  name_experience_exact: '姓名与经历一致',
}

const resumeStatusLabels: Record<CandidateResumeSummaryRecord['status'], string> = {
  uploaded: '已上传',
  queued: '排队中',
  processing: '处理中',
  completed: '已完成',
  failed: '处理失败',
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

function displayName(candidate: CandidateSummaryRecord) {
  return candidate.full_name?.trim() || '姓名待补充'
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback
}

function CandidateIdentity({ candidate }: { candidate: CandidateSummaryRecord }) {
  return (
    <div className="candidate-identity">
      <Avatar size={42} icon={<UserOutlined />} />
      <div className="candidate-identity-main">
        <Space size={8} wrap>
          <Text strong>{displayName(candidate)}</Text>
          <Tag color={candidate.status === 'active' ? 'success' : 'default'}>
            {candidate.status === 'active' ? '有效档案' : '已合并'}
          </Tag>
        </Space>
        <Text type="secondary" copyable={{ text: candidate.candidate_code }}>
          {candidate.candidate_code}
        </Text>
        <div className="candidate-contact-lines">
          <Text type={candidate.phone ? undefined : 'secondary'}>
            <PhoneOutlined /> {candidate.phone || '未识别电话'}
          </Text>
          <Text type={candidate.email ? undefined : 'secondary'} ellipsis>
            <MailOutlined /> {candidate.email || '未识别邮箱'}
          </Text>
        </div>
      </div>
    </div>
  )
}

export function CandidateCenterPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [messageApi, messageContext] = message.useMessage()
  const [phoneForm] = Form.useForm<PhoneUpdateValues>()
  const [candidateStatus, setCandidateStatus] = useState<CandidateListStatus>('active')
  const [searchDraft, setSearchDraft] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE)
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>()
  const [duplicateStatus, setDuplicateStatus] = useState<DuplicateStatusFilter>('pending')
  const [resolutionAction, setResolutionAction] = useState<ResolutionAction>()
  const [targetCandidateId, setTargetCandidateId] = useState<string>()
  const [resolutionReason, setResolutionReason] = useState('')
  const [phoneEditOpen, setPhoneEditOpen] = useState(false)
  const activeView: CandidateCenterView =
    searchParams.get('view') === 'duplicates' ? 'duplicates' : 'profiles'

  const candidateFilters = useMemo(
    () => ({
      status: candidateStatus,
      query: search,
      limit: pageSize,
      offset: (page - 1) * pageSize,
    }),
    [candidateStatus, page, pageSize, search],
  )
  const candidates = useQuery({
    queryKey: ['candidates', candidateFilters],
    queryFn: () => fetchCandidates(candidateFilters),
  })
  const candidateDetail = useQuery({
    queryKey: ['candidate', selectedCandidateId],
    queryFn: () => fetchCandidate(selectedCandidateId!),
    enabled: Boolean(selectedCandidateId),
  })
  const duplicateReviews = useQuery({
    queryKey: ['candidate-duplicate-reviews', duplicateStatus],
    queryFn: () => fetchCandidateDuplicateReviews(duplicateStatus),
    enabled: activeView === 'duplicates',
  })

  function closeResolutionModal() {
    setResolutionAction(undefined)
    setTargetCandidateId(undefined)
    setResolutionReason('')
  }

  async function refreshCandidateData() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['candidates'] }),
      queryClient.invalidateQueries({ queryKey: ['candidate'] }),
      queryClient.invalidateQueries({ queryKey: ['candidate-duplicate-reviews'] }),
    ])
  }

  const dismissMutation = useMutation({
    mutationFn: () =>
      dismissCandidateDuplicateReview(
        resolutionAction!.review.id,
        resolutionReason.trim(),
      ),
    onSuccess: async () => {
      messageApi.success('已判定为不同候选人')
      closeResolutionModal()
      await refreshCandidateData()
    },
    onError: (error) => messageApi.error(errorMessage(error, '保存判定失败')),
  })
  const mergeMutation = useMutation({
    mutationFn: () =>
      mergeCandidateDuplicateReview(
        resolutionAction!.review.id,
        targetCandidateId!,
        resolutionReason.trim(),
      ),
    onSuccess: async (result) => {
      messageApi.success(`档案已合并，保留 ${result.target_candidate.candidate_code}`)
      closeResolutionModal()
      await refreshCandidateData()
    },
    onError: (error) => messageApi.error(errorMessage(error, '合并候选人失败')),
  })
  const phoneUpdateMutation = useMutation({
    mutationFn: (values: PhoneUpdateValues) =>
      updateCandidatePhone(selectedCandidateId!, values.phone, values.reason),
    onSuccess: async (result) => {
      setPhoneEditOpen(false)
      phoneForm.resetFields()
      const revokedMessage = result.revoked_portal_link_count
        ? `，已撤回 ${result.revoked_portal_link_count} 条旧门户链接`
        : ''
      void messageApi.success(`手机号已更新${revokedMessage}`)
      await refreshCandidateData()
    },
    onError: (error) =>
      void messageApi.error(errorMessage(error, '修正候选人手机号失败')),
  })

  function openPhoneEditor() {
    if (!detail) return
    phoneForm.setFieldsValue({ phone: detail.phone ?? '', reason: '' })
    setPhoneEditOpen(true)
  }

  function openResolution(action: ResolutionAction) {
    setResolutionAction(action)
    setResolutionReason('')
    if (action.type === 'merge') {
      setTargetCandidateId(action.review.candidate_a.id)
    } else {
      setTargetCandidateId(undefined)
    }
  }

  function submitResolution() {
    if (!resolutionReason.trim()) {
      messageApi.warning('请填写处理原因')
      return
    }
    if (resolutionAction?.type === 'merge') {
      if (!targetCandidateId) {
        messageApi.warning('请选择保留的候选人档案')
        return
      }
      mergeMutation.mutate()
      return
    }
    dismissMutation.mutate()
  }

  const candidateColumns: ColumnsType<CandidateListItemRecord> = [
    {
      title: '候选人',
      key: 'candidate',
      width: 250,
      render: (_, candidate) => <CandidateIdentity candidate={candidate} />,
    },
    {
      title: '应聘记录',
      key: 'applications',
      width: 110,
      align: 'center',
      render: (_, candidate) => (
        <Text>
          <ApartmentOutlined /> {candidate.application_count}
        </Text>
      ),
    },
    {
      title: '简历',
      key: 'resumes',
      width: 90,
      align: 'center',
      responsive: ['md'],
      render: (_, candidate) => (
        <Text>
          <FileTextOutlined /> {candidate.resume_count}
        </Text>
      ),
    },
    {
      title: '重复提示',
      key: 'duplicates',
      width: 120,
      responsive: ['md'],
      render: (_, candidate) =>
        candidate.pending_duplicate_count ? (
          <Tag color="warning">待确认 {candidate.pending_duplicate_count}</Tag>
        ) : (
          <Text type="secondary">无</Text>
        ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 160,
      responsive: ['lg'],
      render: (value: string) => <Text type="secondary">{formatDateTime(value)}</Text>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 90,
      fixed: 'right',
      render: (_, candidate) => (
        <Button
          type="text"
          icon={<EyeOutlined />}
          onClick={() => setSelectedCandidateId(candidate.id)}
        >
          查看
        </Button>
      ),
    },
  ]

  const applicationColumns: ColumnsType<CandidateApplicationSummaryRecord> = [
    {
      title: '岗位',
      dataIndex: 'job_title',
      render: (value: string, record) => (
        <Space size={6} wrap>
          <Text strong>{value}</Text>
          {record.job_status === 'archived' && <Tag>岗位已归档</Tag>}
        </Space>
      ),
    },
    {
      title: '应聘状态',
      dataIndex: 'status',
      width: 110,
      render: (value: CandidateApplicationSummaryRecord['status']) => (
        <Tag color={value === 'active' ? 'success' : 'default'}>
          {value === 'active' ? '有效应聘' : '已合并'}
        </Tag>
      ),
    },
    {
      title: '当前阶段',
      dataIndex: 'current_stage',
      width: 120,
      responsive: ['md'],
      render: (value: CandidateStage | null) =>
        value ? <Text>{stageLabels[value]}</Text> : <Text type="secondary">尚未进入流程</Text>,
    },
    {
      title: '简历',
      dataIndex: 'document_count',
      width: 70,
      align: 'center',
      responsive: ['md'],
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_, record) => (
        <Button
          type="link"
          icon={<BranchesOutlined />}
          onClick={() => navigate(`/jobs/${record.job_id}/pipeline`)}
        >
          流程
        </Button>
      ),
    },
  ]

  const resumeColumns: ColumnsType<CandidateResumeSummaryRecord> = [
    {
      title: '简历文件',
      dataIndex: 'original_filename',
      ellipsis: true,
      render: (value: string) => (
        <Text>
          <FileTextOutlined /> {value}
        </Text>
      ),
    },
    {
      title: '岗位 / 批次',
      key: 'source',
      responsive: ['md'],
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text>{record.job_title}</Text>
          <Text type="secondary">{record.batch_name || '未命名批次'}</Text>
        </Space>
      ),
    },
    {
      title: '处理状态',
      dataIndex: 'status',
      width: 100,
      responsive: ['md'],
      render: (value: CandidateResumeSummaryRecord['status']) => (
        <Tag color={value === 'completed' ? 'success' : value === 'failed' ? 'error' : 'processing'}>
          {resumeStatusLabels[value]}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_, record) => (
        <Button
          type="link"
          icon={<EyeOutlined />}
          onClick={() =>
            navigate(
              `/jobs/${record.job_id}/batches/${record.batch_id}/documents/${record.id}/history`,
            )
          }
        >
          资料
        </Button>
      ),
    },
  ]

  const detail = candidateDetail.data
  const submitting = dismissMutation.isPending || mergeMutation.isPending

  return (
    <>
      {messageContext}
      <div className="page-heading candidate-center-heading">
        <div>
          <Title level={2}>企业候选人档案</Title>
          <Text type="secondary">{candidates.data?.total ?? 0} 份主档案</Text>
        </div>
      </div>

      <Tabs
        className="candidate-center-tabs"
        activeKey={activeView}
        onChange={(key) => {
          const nextView = key as CandidateCenterView
          setSearchParams(nextView === 'duplicates' ? { view: 'duplicates' } : {})
        }}
        items={[
          { key: 'profiles', label: '候选人档案' },
          { key: 'duplicates', label: '重复确认' },
        ]}
      />

      {activeView === 'profiles' && (
        <section className="candidate-center-section" aria-label="候选人档案列表">
          <div className="candidate-center-toolbar">
            <Input.Search
              aria-label="搜索候选人"
              allowClear
              enterButton={<SearchOutlined />}
              placeholder="姓名、候选人编号、电话或邮箱"
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              onSearch={(value) => {
                setSearch(value.trim())
                setPage(1)
              }}
            />
            <Segmented<CandidateListStatus>
              aria-label="候选人档案状态"
              value={candidateStatus}
              options={[
                { label: '有效档案', value: 'active' },
                { label: '已合并', value: 'merged' },
                { label: '全部', value: 'all' },
              ]}
              onChange={(value) => {
                setCandidateStatus(value)
                setPage(1)
              }}
            />
            <Button
              aria-label="刷新候选人档案"
              icon={<ReloadOutlined />}
              loading={candidates.isFetching}
              onClick={() => void candidates.refetch()}
            />
          </div>

          {candidates.isError && (
            <Alert
              type="error"
              showIcon
              message="候选人档案读取失败"
              description={errorMessage(candidates.error, '请稍后重试')}
            />
          )}
          <Table<CandidateListItemRecord>
            className="candidate-center-table"
            rowKey="id"
            columns={candidateColumns}
            dataSource={candidates.data?.items ?? []}
            loading={candidates.isPending}
            scroll={{ x: 840 }}
            pagination={{
              current: page,
              pageSize,
              total: candidates.data?.total ?? 0,
              showSizeChanger: true,
              pageSizeOptions: [10, 20, 50],
              showTotal: (total) => `共 ${total} 份档案`,
              onChange: (nextPage, nextPageSize) => {
                setPage(nextPageSize === pageSize ? nextPage : 1)
                setPageSize(nextPageSize)
              },
            }}
            locale={{ emptyText: <Empty description="暂无候选人档案" /> }}
          />
        </section>
      )}

      {activeView === 'duplicates' && (
        <section className="candidate-center-section" aria-label="重复候选人确认">
          <div className="candidate-center-toolbar candidate-duplicate-toolbar">
            <Segmented<DuplicateStatusFilter>
              aria-label="重复确认状态"
              value={duplicateStatus}
              options={[
                { label: '待确认', value: 'pending' },
                { label: '已排除', value: 'not_duplicate' },
                { label: '已合并', value: 'merged' },
                { label: '全部', value: 'all' },
              ]}
              onChange={setDuplicateStatus}
            />
            <Button
              aria-label="刷新重复提示"
              icon={<ReloadOutlined />}
              loading={duplicateReviews.isFetching}
              onClick={() => void duplicateReviews.refetch()}
            />
          </div>

          {duplicateReviews.isError && (
            <Alert
              type="error"
              showIcon
              message="重复提示读取失败"
              description={errorMessage(duplicateReviews.error, '请稍后重试')}
            />
          )}
          {duplicateReviews.isPending && <Skeleton active paragraph={{ rows: 10 }} />}
          {!duplicateReviews.isPending && !duplicateReviews.data?.length && (
            <Empty description="当前没有重复候选人提示" />
          )}
          <div className="candidate-duplicate-list">
            {(duplicateReviews.data ?? []).map((review) => (
              <article className="candidate-duplicate-review" key={review.id}>
                <header className="candidate-duplicate-review-header">
                  <Space wrap>
                    <Tag color={review.confidence === 'strong' ? 'error' : 'warning'}>
                      {review.confidence === 'strong' ? '强重复信号' : '弱重复信号'}
                    </Tag>
                    {review.signals.map((signal) => (
                      <Tag key={signal}>{signalLabels[signal] || signal}</Tag>
                    ))}
                  </Space>
                  <Text type="secondary">{formatDateTime(review.created_at)}</Text>
                </header>
                <div className="candidate-duplicate-pair">
                  <div className="candidate-duplicate-person">
                    <CandidateIdentity candidate={review.candidate_a} />
                    <Text type="secondary">
                      {review.candidate_a.application_count} 条应聘 ·{' '}
                      {review.candidate_a.resume_count} 份简历
                    </Text>
                  </div>
                  <div className="candidate-duplicate-divider" aria-hidden="true">
                    <MergeCellsOutlined />
                  </div>
                  <div className="candidate-duplicate-person">
                    <CandidateIdentity candidate={review.candidate_b} />
                    <Text type="secondary">
                      {review.candidate_b.application_count} 条应聘 ·{' '}
                      {review.candidate_b.resume_count} 份简历
                    </Text>
                  </div>
                </div>
                <footer className="candidate-duplicate-review-footer">
                  {review.status === 'pending' ? (
                    <Space wrap>
                      <Button
                        icon={<StopOutlined />}
                        onClick={() => openResolution({ type: 'dismiss', review })}
                      >
                        不是同一人
                      </Button>
                      <Button
                        type="primary"
                        icon={<MergeCellsOutlined />}
                        onClick={() => openResolution({ type: 'merge', review })}
                      >
                        合并档案
                      </Button>
                    </Space>
                  ) : (
                    <Space direction="vertical" size={2}>
                      <Tag color={review.status === 'merged' ? 'success' : 'default'}>
                        {review.status === 'merged' ? '已合并' : '已排除'}
                      </Tag>
                      <Text>{review.resolution_note || '未填写处理原因'}</Text>
                      {review.resolved_at && (
                        <Text type="secondary">{formatDateTime(review.resolved_at)}</Text>
                      )}
                    </Space>
                  )}
                </footer>
              </article>
            ))}
          </div>
        </section>
      )}

      <Drawer
        className="candidate-detail-drawer"
        width={860}
        open={Boolean(selectedCandidateId)}
        title={detail ? `${displayName(detail)} · ${detail.candidate_code}` : '候选人详情'}
        onClose={() => setSelectedCandidateId(undefined)}
      >
        {candidateDetail.isPending && <Skeleton active paragraph={{ rows: 12 }} />}
        {candidateDetail.isError && (
          <Alert
            type="error"
            showIcon
            message="候选人详情读取失败"
            description={errorMessage(candidateDetail.error, '请稍后重试')}
          />
        )}
        {detail && (
          <CandidateDetailContent
            detail={detail}
            applicationColumns={applicationColumns}
            resumeColumns={resumeColumns}
            onOpenCandidate={setSelectedCandidateId}
            onEditPhone={openPhoneEditor}
          />
        )}
      </Drawer>

      <Modal
        open={phoneEditOpen}
        title="修正候选人手机号"
        okText="确认修改"
        cancelText="取消"
        confirmLoading={phoneUpdateMutation.isPending}
        onOk={() => phoneForm.submit()}
        onCancel={() => {
          setPhoneEditOpen(false)
          phoneForm.resetFields()
        }}
        destroyOnHidden
      >
        <Alert
          type="warning"
          showIcon
          message="修改后，候选人的未撤回门户链接会立即失效。"
        />
        <Form<PhoneUpdateValues>
          form={phoneForm}
          layout="vertical"
          onFinish={(values) => phoneUpdateMutation.mutate(values)}
        >
          <Form.Item
            label="手机号"
            name="phone"
            rules={[{ required: true, whitespace: true, message: '请输入有效手机号' }]}
          >
            <Input maxLength={50} autoComplete="tel" />
          </Form.Item>
          <Form.Item
            label="修改原因"
            name="reason"
            rules={[{ required: true, whitespace: true, message: '请填写修改原因' }]}
          >
            <Input.TextArea rows={4} maxLength={2_000} showCount />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={Boolean(resolutionAction)}
        title={resolutionAction?.type === 'merge' ? '合并候选人档案' : '确认不是同一人'}
        okText={resolutionAction?.type === 'merge' ? '确认合并' : '确认排除'}
        cancelText="取消"
        confirmLoading={submitting}
        okButtonProps={{
          disabled:
            !resolutionReason.trim() ||
            (resolutionAction?.type === 'merge' && !targetCandidateId),
        }}
        onOk={submitResolution}
        onCancel={closeResolutionModal}
        destroyOnHidden
      >
        {resolutionAction?.type === 'merge' && (
          <>
            <Alert
              type="warning"
              showIcon
              message="合并后不能在页面中撤销"
              description="应聘、简历、筛选、流程和面试历史都会保留，并统一归入所选主档案。"
              className="candidate-resolution-alert"
            />
            <Text strong>保留主档案</Text>
            <Radio.Group
              className="candidate-merge-choices"
              value={targetCandidateId}
              onChange={(event) => setTargetCandidateId(event.target.value as string)}
            >
              {[resolutionAction.review.candidate_a, resolutionAction.review.candidate_b].map(
                (candidate) => (
                  <Radio.Button key={candidate.id} value={candidate.id}>
                    <span>{displayName(candidate)}</span>
                    <small>{candidate.candidate_code}</small>
                  </Radio.Button>
                ),
              )}
            </Radio.Group>
          </>
        )}
        <label className="candidate-resolution-reason" htmlFor="candidate-resolution-reason">
          <Text strong>处理原因</Text>
          <Input.TextArea
            id="candidate-resolution-reason"
            aria-label="处理原因"
            rows={4}
            maxLength={2000}
            showCount
            value={resolutionReason}
            placeholder="填写人工核对依据"
            onChange={(event) => setResolutionReason(event.target.value)}
          />
        </label>
      </Modal>
    </>
  )
}

function CandidateDetailContent({
  detail,
  applicationColumns,
  resumeColumns,
  onOpenCandidate,
  onEditPhone,
}: {
  detail: CandidateDetailRecord
  applicationColumns: ColumnsType<CandidateApplicationSummaryRecord>
  resumeColumns: ColumnsType<CandidateResumeSummaryRecord>
  onOpenCandidate: (candidateId: string) => void
  onEditPhone: () => void
}) {
  return (
    <div className="candidate-detail-content">
      {detail.status === 'active' && (
        <div className="candidate-detail-actions">
          <Button icon={<EditOutlined />} onClick={onEditPhone}>
            修正手机号
          </Button>
        </div>
      )}
      <Descriptions column={{ xs: 1, sm: 2 }} bordered size="small">
        <Descriptions.Item label="档案状态">
          <Tag color={detail.status === 'active' ? 'success' : 'default'}>
            {detail.status === 'active' ? '有效档案' : '已合并'}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="候选人编号">{detail.candidate_code}</Descriptions.Item>
        <Descriptions.Item label="联系电话">{detail.phone || '未识别'}</Descriptions.Item>
        <Descriptions.Item label="联系邮箱">{detail.email || '未识别'}</Descriptions.Item>
        <Descriptions.Item label="应聘记录">{detail.application_count}</Descriptions.Item>
        <Descriptions.Item label="简历附件">{detail.resume_count}</Descriptions.Item>
        <Descriptions.Item label="更新时间" span={2}>
          {formatDateTime(detail.updated_at)}
        </Descriptions.Item>
      </Descriptions>

      {detail.status === 'merged' && detail.merged_into_candidate_id && (
        <Alert
          type="info"
          showIcon
          message="该档案已并入其他候选人主档案"
          description={
            <Button
              type="link"
              className="candidate-merged-target-link"
              onClick={() => onOpenCandidate(detail.merged_into_candidate_id!)}
            >
              查看保留的主档案
            </Button>
          }
        />
      )}

      <section>
        <Title level={4}>应聘历史</Title>
        <Table<CandidateApplicationSummaryRecord>
          rowKey="id"
          size="small"
          columns={applicationColumns}
          dataSource={detail.applications}
          pagination={false}
          scroll={{ x: 680 }}
          locale={{ emptyText: '暂无应聘记录' }}
        />
      </section>

      <section>
        <Title level={4}>简历记录</Title>
        <Table<CandidateResumeSummaryRecord>
          rowKey="id"
          size="small"
          columns={resumeColumns}
          dataSource={detail.resumes}
          pagination={false}
          scroll={{ x: 620 }}
          locale={{ emptyText: '暂无简历记录' }}
        />
      </section>
    </div>
  )
}
