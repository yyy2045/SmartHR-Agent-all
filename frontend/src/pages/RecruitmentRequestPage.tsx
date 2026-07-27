import {
  CheckOutlined,
  EditOutlined,
  EyeOutlined,
  FileAddOutlined,
  SendOutlined,
  StopOutlined,
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

import {
  ApiError,
  createRecruitmentRequest,
  createRecruitmentRequestVersion,
  decideRecruitmentRequest,
  fetchRecruitmentRequests,
  fetchUserOptions,
  submitRecruitmentRequest,
  type RecruitmentRequestContentInput,
  type RecruitmentRequestDecision,
  type RecruitmentRequestPriority,
  type RecruitmentRequestRecord,
  type RecruitmentRequestStatus,
  type UserOption,
} from '../api/client'
import { useAuth } from '../auth/context'

const { Title, Text, Paragraph } = Typography

const statusMeta: Record<RecruitmentRequestStatus, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  pending_approval: { label: '审批中', color: 'processing' },
  approved: { label: '已批准', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
  converted: { label: '已转职位', color: 'cyan' },
}

const priorityMeta: Record<RecruitmentRequestPriority, { label: string; color: string }> = {
  urgent: { label: '紧急', color: 'error' },
  high: { label: '高', color: 'warning' },
  normal: { label: '中', color: 'blue' },
  low: { label: '低', color: 'default' },
}

type StatusFilter = 'all' | RecruitmentRequestStatus

interface RecruitmentRequestFormValues extends RecruitmentRequestContentInput {
  requester_id?: string
  recruiter_id?: string
}

interface DecisionFormValues {
  comment: string
}

interface DecisionTarget {
  request: RecruitmentRequestRecord
  decision: RecruitmentRequestDecision
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(value))
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

function formatSalary(minimum: number, maximum: number) {
  return `${minimum.toLocaleString('zh-CN')} - ${maximum.toLocaleString('zh-CN')} 元/月`
}

function defaultTargetDate() {
  const target = new Date()
  target.setDate(target.getDate() + 30)
  return target.toISOString().slice(0, 10)
}

function userOptions(users: UserOption[] | undefined) {
  return (users ?? []).map((user) => ({
    value: user.id,
    label: `${user.display_name}（${user.username}）`,
  }))
}

function requestContent(values: RecruitmentRequestFormValues): RecruitmentRequestContentInput {
  return {
    job_title: values.job_title,
    headcount: values.headcount,
    reason: values.reason,
    priority: values.priority,
    target_start_date: values.target_start_date,
    salary_min: values.salary_min,
    salary_max: values.salary_max,
    notes: values.notes ?? '',
  }
}

export function RecruitmentRequestPage() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const [messageApi, messageContext] = message.useMessage()
  const [modal, modalContext] = Modal.useModal()
  const [requestForm] = Form.useForm<RecruitmentRequestFormValues>()
  const [decisionForm] = Form.useForm<DecisionFormValues>()
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [selectedId, setSelectedId] = useState<string>()
  const [formOpen, setFormOpen] = useState(false)
  const [editingRequest, setEditingRequest] = useState<RecruitmentRequestRecord>()
  const [decisionTarget, setDecisionTarget] = useState<DecisionTarget>()
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID())
  const isAdministrator = auth.user?.roles.includes('administrator') ?? false
  const isHiringManager = auth.user?.roles.includes('hiring_manager') ?? false
  const canCreate = isAdministrator || isHiringManager
  const canApprove =
    isAdministrator || (auth.user?.roles.includes('approver') ?? false)

  const requests = useQuery({
    queryKey: ['recruitment-requests'],
    queryFn: () => fetchRecruitmentRequests(),
  })
  const recruiters = useQuery({
    queryKey: ['user-options', 'recruiter'],
    queryFn: () => fetchUserOptions('recruiter'),
    enabled: canCreate,
  })
  const hiringManagers = useQuery({
    queryKey: ['user-options', 'hiring_manager'],
    queryFn: () => fetchUserOptions('hiring_manager'),
    enabled: isAdministrator,
  })

  const selectedRequest = requests.data?.find((request) => request.id === selectedId)
  const visibleRequests = useMemo(
    () =>
      (requests.data ?? []).filter(
        (request) => statusFilter === 'all' || request.status === statusFilter,
      ),
    [requests.data, statusFilter],
  )
  const counts = useMemo(() => {
    const values = Object.fromEntries(
      Object.keys(statusMeta).map((status) => [status, 0]),
    ) as Record<RecruitmentRequestStatus, number>
    for (const request of requests.data ?? []) values[request.status] += 1
    return values
  }, [requests.data])

  function updateRequestCache(saved: RecruitmentRequestRecord) {
    queryClient.setQueryData<RecruitmentRequestRecord[]>(
      ['recruitment-requests'],
      (current = []) => {
        const exists = current.some((item) => item.id === saved.id)
        return exists
          ? current.map((item) => (item.id === saved.id ? saved : item))
          : [saved, ...current]
      },
    )
    void queryClient.invalidateQueries({ queryKey: ['recruitment-requests'] })
  }

  const saveMutation = useMutation({
    mutationFn: (values: RecruitmentRequestFormValues) => {
      const content = requestContent(values)
      if (editingRequest) {
        return createRecruitmentRequestVersion(editingRequest.id, {
          ...content,
          source_version_id: editingRequest.current_version.id,
        })
      }
      if (!values.recruiter_id) throw new Error('请选择招聘专员')
      return createRecruitmentRequest({
        ...content,
        idempotency_key: idempotencyKey,
        recruiter_id: values.recruiter_id,
        ...(isAdministrator && values.requester_id
          ? { requester_id: values.requester_id }
          : {}),
      })
    },
    onSuccess: (saved) => {
      updateRequestCache(saved)
      setSelectedId(saved.id)
      setFormOpen(false)
      messageApi.success(editingRequest ? '已保存为新版本' : '招聘需求已创建')
    },
  })
  const submitMutation = useMutation({
    mutationFn: (request: RecruitmentRequestRecord) =>
      submitRecruitmentRequest(request.id, request.current_version.id),
    onSuccess: (saved) => {
      updateRequestCache(saved)
      messageApi.success('招聘需求已提交审批')
    },
  })
  const decisionMutation = useMutation({
    mutationFn: ({ target, comment }: { target: DecisionTarget; comment: string }) =>
      decideRecruitmentRequest(
        target.request.id,
        target.request.current_version.id,
        target.decision,
        comment,
      ),
    onSuccess: (saved, variables) => {
      updateRequestCache(saved)
      setDecisionTarget(undefined)
      decisionForm.resetFields()
      messageApi.success(variables.target.decision === 'approved' ? '需求已批准' : '需求已驳回')
    },
  })

  function openCreateForm() {
    const nextKey = crypto.randomUUID()
    setIdempotencyKey(nextKey)
    setEditingRequest(undefined)
    saveMutation.reset()
    requestForm.resetFields()
    requestForm.setFieldsValue({
      headcount: 1,
      priority: 'normal',
      target_start_date: defaultTargetDate(),
      notes: '',
    })
    setFormOpen(true)
  }

  function openEditForm(request: RecruitmentRequestRecord) {
    const version = request.current_version
    setEditingRequest(request)
    saveMutation.reset()
    requestForm.resetFields()
    requestForm.setFieldsValue({
      job_title: version.job_title,
      headcount: version.headcount,
      reason: version.reason,
      priority: version.priority,
      target_start_date: version.target_start_date,
      salary_min: version.salary_min,
      salary_max: version.salary_max,
      notes: version.notes,
    })
    setFormOpen(true)
  }

  function canEdit(request: RecruitmentRequestRecord) {
    const ownsRequest =
      isAdministrator ||
      (isHiringManager && request.requester.id === auth.user?.id)
    return ownsRequest && ['draft', 'rejected'].includes(request.status)
  }

  function confirmSubmit(request: RecruitmentRequestRecord) {
    modal.confirm({
      title: '提交招聘需求审批？',
      content: `将提交 V${request.current_version_number}，提交后审批完成前不能修改。`,
      okText: '确认提交',
      cancelText: '取消',
      onOk: () => submitMutation.mutateAsync(request),
    })
  }

  function openDecision(request: RecruitmentRequestRecord, decision: RecruitmentRequestDecision) {
    decisionMutation.reset()
    decisionForm.resetFields()
    setDecisionTarget({ request, decision })
  }

  const columns: ColumnsType<RecruitmentRequestRecord> = [
    {
      title: '招聘需求',
      key: 'request',
      render: (_, request) => (
        <div className="request-title-cell">
          <Text strong>{request.current_version.job_title}</Text>
          <Text type="secondary">V{request.current_version_number}</Text>
        </div>
      ),
    },
    {
      title: '优先级',
      key: 'priority',
      width: 90,
      render: (_, request) => {
        const meta = priorityMeta[request.current_version.priority]
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
      responsive: ['sm'],
    },
    {
      title: '人数',
      key: 'headcount',
      width: 80,
      render: (_, request) => `${request.current_version.headcount} 人`,
      responsive: ['md'],
    },
    {
      title: '用人经理 / 招聘专员',
      key: 'owners',
      width: 210,
      render: (_, request) => (
        <div className="request-owner-cell">
          <Text>{request.requester.display_name}</Text>
          <Text type="secondary">{request.recruiter.display_name}</Text>
        </div>
      ),
      responsive: ['lg'],
    },
    {
      title: '期望到岗',
      key: 'target_start_date',
      width: 130,
      render: (_, request) => formatDate(request.current_version.target_start_date),
      responsive: ['md'],
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (value: RecruitmentRequestStatus) => (
        <Tag color={statusMeta[value].color}>{statusMeta[value].label}</Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 92,
      fixed: 'right',
      render: (_, request) => (
        <Button type="link" icon={<EyeOutlined />} onClick={() => setSelectedId(request.id)}>
          查看
        </Button>
      ),
    },
  ]

  const mutationError =
    saveMutation.error ?? submitMutation.error ?? decisionMutation.error
  const optionError = recruiters.error ?? hiringManagers.error

  return (
    <>
      {messageContext}
      {modalContext}
      <div className="page-heading">
        <div>
          <Title level={2}>招聘需求</Title>
          <Text type="secondary">从用人申请到批准建岗，保留完整版本与审批记录</Text>
        </div>
        {canCreate && (
          <Button type="primary" icon={<FileAddOutlined />} onClick={openCreateForm}>
            新建需求
          </Button>
        )}
      </div>

      {mutationError && (
        <Alert
          type="error"
          showIcon
          closable
          className="page-alert"
          message={
            mutationError instanceof ApiError ? mutationError.message : mutationError.message
          }
        />
      )}
      {optionError && canCreate && (
        <Alert
          type="error"
          showIcon
          className="page-alert"
          message="无法读取需求负责人选项"
          description={optionError.message}
        />
      )}

      {requests.isPending && (
        <section className="panel-card">
          <Skeleton active paragraph={{ rows: 8 }} />
        </section>
      )}
      {requests.isError && (
        <Alert
          type="error"
          showIcon
          message="无法读取招聘需求"
          description={requests.error.message}
          action={<Button onClick={() => void requests.refetch()}>重试</Button>}
        />
      )}
      {requests.isSuccess && (
        <section className="request-workspace" aria-label="招聘需求列表">
          <div className="request-filter-bar">
            <Segmented<StatusFilter>
              block
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { label: `全部 ${requests.data.length}`, value: 'all' },
                { label: `草稿 ${counts.draft}`, value: 'draft' },
                { label: `审批中 ${counts.pending_approval}`, value: 'pending_approval' },
                { label: `已批准 ${counts.approved}`, value: 'approved' },
                { label: `已驳回 ${counts.rejected}`, value: 'rejected' },
                { label: `已转职位 ${counts.converted}`, value: 'converted' },
              ]}
            />
          </div>
          {visibleRequests.length === 0 ? (
            <Empty
              className="request-empty"
              description={statusFilter === 'all' ? '暂无招聘需求' : '当前状态没有需求'}
            >
              {canCreate && statusFilter === 'all' && (
                <Button type="primary" icon={<FileAddOutlined />} onClick={openCreateForm}>
                  创建第一条需求
                </Button>
              )}
            </Empty>
          ) : (
            <Table<RecruitmentRequestRecord>
              rowKey="id"
              columns={columns}
              dataSource={visibleRequests}
              pagination={{ pageSize: 10, hideOnSinglePage: true }}
              scroll={{ x: 760 }}
              rowClassName={(request) =>
                request.id === selectedId ? 'request-row-selected' : ''
              }
            />
          )}
        </section>
      )}

      <Drawer
        width={720}
        open={Boolean(selectedRequest)}
        onClose={() => setSelectedId(undefined)}
        title={
          selectedRequest ? (
            <Space wrap>
              <span>{selectedRequest.current_version.job_title}</span>
              <Tag color={statusMeta[selectedRequest.status].color}>
                {statusMeta[selectedRequest.status].label}
              </Tag>
            </Space>
          ) : null
        }
      >
        {selectedRequest && (
          <div className="request-detail">
            <div className="request-detail-actions">
              <Space wrap>
                {canEdit(selectedRequest) && (
                  <Button icon={<EditOutlined />} onClick={() => openEditForm(selectedRequest)}>
                    新建修改版本
                  </Button>
                )}
                {canEdit(selectedRequest) && selectedRequest.status === 'draft' && (
                  <Button
                    type="primary"
                    icon={<SendOutlined />}
                    loading={submitMutation.isPending}
                    onClick={() => confirmSubmit(selectedRequest)}
                  >
                    提交审批
                  </Button>
                )}
                {canApprove && selectedRequest.status === 'pending_approval' && (
                  <>
                    <Button
                      type="primary"
                      icon={<CheckOutlined />}
                      onClick={() => openDecision(selectedRequest, 'approved')}
                    >
                      批准
                    </Button>
                    <Button
                      danger
                      icon={<StopOutlined />}
                      onClick={() => openDecision(selectedRequest, 'rejected')}
                    >
                      驳回
                    </Button>
                  </>
                )}
              </Space>
            </div>

            {selectedRequest.status === 'rejected' && canEdit(selectedRequest) && (
              <Alert
                type="warning"
                showIcon
                message="该需求已被驳回，请创建修改版本后重新提交"
              />
            )}

            <Descriptions
              title={`当前版本 V${selectedRequest.current_version_number}`}
              bordered
              size="small"
              column={{ xs: 1, sm: 2 }}
            >
              <Descriptions.Item label="招聘人数">
                {selectedRequest.current_version.headcount} 人
              </Descriptions.Item>
              <Descriptions.Item label="优先级">
                {priorityMeta[selectedRequest.current_version.priority].label}
              </Descriptions.Item>
              <Descriptions.Item label="期望到岗">
                {formatDate(selectedRequest.current_version.target_start_date)}
              </Descriptions.Item>
              <Descriptions.Item label="月薪范围">
                {formatSalary(
                  selectedRequest.current_version.salary_min,
                  selectedRequest.current_version.salary_max,
                )}
              </Descriptions.Item>
              <Descriptions.Item label="用人经理">
                {selectedRequest.requester.display_name}
              </Descriptions.Item>
              <Descriptions.Item label="招聘专员">
                {selectedRequest.recruiter.display_name}
              </Descriptions.Item>
              <Descriptions.Item label="招聘原因" span={{ xs: 1, sm: 2 }}>
                {selectedRequest.current_version.reason}
              </Descriptions.Item>
              <Descriptions.Item label="备注" span={{ xs: 1, sm: 2 }}>
                {selectedRequest.current_version.notes || '无'}
              </Descriptions.Item>
            </Descriptions>

            <Divider />
            <Title level={4}>审批记录</Title>
            {selectedRequest.approvals.length === 0 ? (
              <Text type="secondary">尚无审批记录</Text>
            ) : (
              <Timeline
                items={[...selectedRequest.approvals].reverse().map((approval) => ({
                  color: approval.decision === 'approved' ? 'green' : 'red',
                  children: (
                    <div className="request-timeline-item">
                      <Space wrap>
                        <Tag color={approval.decision === 'approved' ? 'success' : 'error'}>
                          {approval.decision === 'approved' ? '批准' : '驳回'}
                        </Tag>
                        <Text strong>{approval.approver_display_name}</Text>
                        <Text type="secondary">{formatDateTime(approval.decided_at)}</Text>
                      </Space>
                      <Paragraph>{approval.comment || '无审批意见'}</Paragraph>
                    </div>
                  ),
                }))}
              />
            )}

            <Divider />
            <Title level={4}>版本历史</Title>
            <Timeline
              items={[...selectedRequest.versions].reverse().map((version) => ({
                color:
                  version.version_number === selectedRequest.current_version_number
                    ? 'blue'
                    : 'gray',
                children: (
                  <div className="request-timeline-item">
                    <Space wrap>
                      <Text strong>V{version.version_number}</Text>
                      <Text>{version.job_title}</Text>
                      <Text type="secondary">
                        {version.created_by_display_name} · {formatDateTime(version.created_at)}
                      </Text>
                    </Space>
                    <Paragraph type="secondary">
                      {version.headcount} 人 · {priorityMeta[version.priority].label}优先级 ·{' '}
                      {formatSalary(version.salary_min, version.salary_max)}
                    </Paragraph>
                  </div>
                ),
              }))}
            />
          </div>
        )}
      </Drawer>

      <Modal
        width={760}
        open={formOpen}
        title={editingRequest ? '创建招聘需求新版本' : '新建招聘需求'}
        okText={editingRequest ? '保存新版本' : '创建草稿'}
        cancelText="取消"
        confirmLoading={saveMutation.isPending}
        forceRender
        onCancel={() => setFormOpen(false)}
        onOk={() => requestForm.submit()}
      >
        <Form<RecruitmentRequestFormValues>
          form={requestForm}
          layout="vertical"
          requiredMark={false}
          onFinish={(values) => saveMutation.mutate(values)}
        >
          {!editingRequest && (
            <div className="request-form-grid">
              {isAdministrator && (
                <Form.Item
                  label="用人经理"
                  name="requester_id"
                  rules={[{ required: true, message: '请选择用人经理' }]}
                >
                  <Select
                    showSearch
                    optionFilterProp="label"
                    options={userOptions(hiringManagers.data)}
                    loading={hiringManagers.isPending}
                    placeholder="选择需求发起人"
                  />
                </Form.Item>
              )}
              <Form.Item
                label="负责招聘专员"
                name="recruiter_id"
                rules={[{ required: true, message: '请选择招聘专员' }]}
              >
                <Select
                  showSearch
                  optionFilterProp="label"
                  options={userOptions(recruiters.data)}
                  loading={recruiters.isPending}
                  placeholder="选择后续负责建岗的招聘专员"
                />
              </Form.Item>
            </div>
          )}
          <div className="request-form-grid">
            <Form.Item
              label="职位名称"
              name="job_title"
              rules={[{ required: true, whitespace: true, message: '请输入职位名称' }]}
            >
              <Input maxLength={200} showCount placeholder="例如：高级后端工程师" />
            </Form.Item>
            <Form.Item
              label="招聘人数"
              name="headcount"
              rules={[{ required: true, message: '请输入招聘人数' }]}
            >
              <InputNumber min={1} max={10_000} precision={0} />
            </Form.Item>
            <Form.Item
              label="优先级"
              name="priority"
              rules={[{ required: true, message: '请选择优先级' }]}
            >
              <Select
                options={Object.entries(priorityMeta).map(([value, meta]) => ({
                  value,
                  label: meta.label,
                }))}
              />
            </Form.Item>
            <Form.Item
              label="期望到岗日期"
              name="target_start_date"
              rules={[{ required: true, message: '请选择期望到岗日期' }]}
            >
              <Input type="date" />
            </Form.Item>
            <Form.Item
              label="月薪下限"
              name="salary_min"
              rules={[{ required: true, message: '请输入月薪下限' }]}
            >
              <InputNumber min={0} max={100_000_000} precision={0} />
            </Form.Item>
            <Form.Item
              label="月薪上限"
              name="salary_max"
              dependencies={['salary_min']}
              rules={[
                { required: true, message: '请输入月薪上限' },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (value === undefined || value >= getFieldValue('salary_min')) {
                      return Promise.resolve()
                    }
                    return Promise.reject(new Error('月薪上限不能低于下限'))
                  },
                }),
              ]}
            >
              <InputNumber min={0} max={100_000_000} precision={0} />
            </Form.Item>
          </div>
          <Form.Item
            label="招聘原因"
            name="reason"
            rules={[{ required: true, whitespace: true, message: '请填写招聘原因' }]}
          >
            <Input.TextArea rows={4} maxLength={5_000} showCount />
          </Form.Item>
          <Form.Item label="补充说明" name="notes">
            <Input.TextArea rows={3} maxLength={5_000} showCount />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={Boolean(decisionTarget)}
        title={decisionTarget?.decision === 'approved' ? '批准招聘需求' : '驳回招聘需求'}
        okText={decisionTarget?.decision === 'approved' ? '确认批准' : '确认驳回'}
        okButtonProps={{ danger: decisionTarget?.decision === 'rejected' }}
        confirmLoading={decisionMutation.isPending}
        onCancel={() => setDecisionTarget(undefined)}
        onOk={() => decisionForm.submit()}
      >
        <Form<DecisionFormValues>
          form={decisionForm}
          layout="vertical"
          initialValues={{ comment: '' }}
          onFinish={(values) => {
            if (decisionTarget) {
              decisionMutation.mutate({ target: decisionTarget, comment: values.comment ?? '' })
            }
          }}
        >
          <Form.Item
            label="审批意见"
            name="comment"
            rules={[
              {
                required: decisionTarget?.decision === 'rejected',
                whitespace: true,
                message: '驳回时必须填写审批意见',
              },
            ]}
          >
            <Input.TextArea
              rows={4}
              maxLength={5_000}
              showCount
              placeholder={
                decisionTarget?.decision === 'approved'
                  ? '可选，填写批准意见'
                  : '说明需要修改的内容'
              }
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
