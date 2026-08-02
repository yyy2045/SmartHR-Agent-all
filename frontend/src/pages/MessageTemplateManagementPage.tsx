import {
  EditOutlined,
  EyeOutlined,
  PlusOutlined,
  PoweroffOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { useMemo, useState } from 'react'

import {
  activateMessageTemplate,
  ApiError,
  createMessageTemplate,
  createMessageTemplateVersion,
  deactivateMessageTemplate,
  fetchMessageTemplate,
  fetchMessageTemplates,
  type MessageTemplateCreateInput,
  type MessageTemplateRecord,
  type MessageTemplateStatus,
  type MessageTemplateSummaryRecord,
  type MessageTemplateType,
  type MessageTemplateVersionCreateInput,
} from '../api/client'

const { Text, Title, Paragraph } = Typography
const PAGE_SIZE = 20

const templateTypeOptions: { label: string; value: MessageTemplateType }[] = [
  { value: 'interview_invitation', label: '面试通知' },
  { value: 'interview_reschedule', label: '面试改期' },
  { value: 'interview_cancellation', label: '面试取消' },
  { value: 'meeting_details', label: '会议信息' },
  { value: 'offer_notification', label: 'Offer 通知' },
  { value: 'offer_reminder', label: 'Offer 提醒' },
  { value: 'onboarding_date_confirmation', label: '入职日期确认' },
]

const templateTypeLabels = Object.fromEntries(
  templateTypeOptions.map((item) => [item.value, item.label]),
) as Record<MessageTemplateType, string>

const statusOptions: { label: string; value: MessageTemplateStatus }[] = [
  { value: 'active', label: '只看启用' },
  { value: 'inactive', label: '只看停用' },
  { value: 'all', label: '全部状态' },
]

interface TemplateFormValues {
  templateType: MessageTemplateType
  name: string
  subject: string
  body: string
  variablesText?: string
}

function parseVariables(value?: string) {
  return Array.from(
    new Set(
      (value ?? '')
        .split(/[\s,，]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  )
}

function variablesToText(variables: string[]) {
  return variables.join('\n')
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

function statusTag(status: MessageTemplateSummaryRecord['status']) {
  return status === 'active' ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>
}

function templateMutationError(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback
}

export function MessageTemplateManagementPage() {
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [status, setStatus] = useState<MessageTemplateStatus>('all')
  const [templateType, setTemplateType] = useState<MessageTemplateType | undefined>()
  const [query, setQuery] = useState('')
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState<MessageTemplateRecord | null>(null)
  const [createForm] = Form.useForm<TemplateFormValues>()
  const [editForm] = Form.useForm<TemplateFormValues>()

  const templates = useQuery({
    queryKey: ['message-templates', { status, templateType, query }],
    queryFn: () =>
      fetchMessageTemplates({
        status,
        templateType,
        query: query.trim() || undefined,
        limit: PAGE_SIZE,
        offset: 0,
      }),
    staleTime: 15_000,
  })

  const selectedTemplate = useQuery({
    queryKey: ['message-template', selectedTemplateId],
    queryFn: () => fetchMessageTemplate(selectedTemplateId!),
    enabled: Boolean(selectedTemplateId),
  })

  const invalidateTemplates = async (templateId?: string) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['message-templates'] }),
      templateId
        ? queryClient.invalidateQueries({ queryKey: ['message-template', templateId] })
        : Promise.resolve(),
    ])
  }

  const createMutation = useMutation({
    mutationFn: (input: MessageTemplateCreateInput) => createMessageTemplate(input),
    onSuccess: async (template) => {
      await invalidateTemplates(template.id)
      setCreateOpen(false)
      createForm.resetFields()
      setSelectedTemplateId(template.id)
      messageApi.success('沟通模板已创建')
    },
  })

  const versionMutation = useMutation({
    mutationFn: ({
      templateId,
      input,
    }: {
      templateId: string
      input: MessageTemplateVersionCreateInput
    }) => createMessageTemplateVersion(templateId, input),
    onSuccess: async (template) => {
      await invalidateTemplates(template.id)
      setEditingTemplate(null)
      editForm.resetFields()
      setSelectedTemplateId(template.id)
      messageApi.success('已保存为新版本')
    },
  })

  const statusMutation = useMutation({
    mutationFn: ({
      template,
      targetStatus,
    }: {
      template: MessageTemplateSummaryRecord
      targetStatus: Exclude<MessageTemplateStatus, 'all'>
    }) => {
      const input = { expectedVersion: template.resource_version }
      return targetStatus === 'active'
        ? activateMessageTemplate(template.id, input)
        : deactivateMessageTemplate(template.id, input)
    },
    onSuccess: async (template) => {
      await invalidateTemplates(template.id)
      messageApi.success(template.status === 'active' ? '模板已启用' : '模板已停用')
    },
  })

  const mutationError = createMutation.error ?? versionMutation.error ?? statusMutation.error

  const tableData = templates.data?.items ?? []

  const templateTypeFilterOptions = useMemo(
    () => [{ value: '', label: '全部类型' }, ...templateTypeOptions],
    [],
  )

  function openEdit(template: MessageTemplateRecord) {
    setEditingTemplate(template)
    editForm.setFieldsValue({
      templateType: template.template_type,
      name: template.name,
      subject: template.current_version.subject,
      body: template.current_version.body,
      variablesText: variablesToText(template.current_version.variables),
    })
  }

  function submitCreate(values: TemplateFormValues) {
    createMutation.mutate({
      templateType: values.templateType,
      name: values.name,
      subject: values.subject,
      body: values.body,
      variables: parseVariables(values.variablesText),
    })
  }

  function submitVersion(values: TemplateFormValues) {
    if (!editingTemplate) return
    versionMutation.mutate({
      templateId: editingTemplate.id,
      input: {
        expectedVersion: editingTemplate.resource_version,
        subject: values.subject,
        body: values.body,
        variables: parseVariables(values.variablesText),
      },
    })
  }

  function toggleStatus(template: MessageTemplateSummaryRecord) {
    const targetStatus = template.status === 'active' ? 'inactive' : 'active'
    statusMutation.mutate({ template, targetStatus })
  }

  return (
    <>
      {contextHolder}
      <div className="message-template-page">
        <div className="page-heading">
          <div>
            <Title level={2}>沟通模板</Title>
            <Text type="secondary">
              管理面试、Offer 和入职沟通文案；修改模板会创建新版本，历史版本不会被覆盖。
            </Text>
          </div>
          <Space wrap>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => void templates.refetch()}
              loading={templates.isFetching}
            >
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              创建模板
            </Button>
          </Space>
        </div>

        {mutationError && (
          <Alert
            type="error"
            showIcon
            closable
            className="page-alert"
            message={templateMutationError(mutationError, '沟通模板操作失败')}
          />
        )}

        {templates.isError && (
          <Alert
            type="error"
            showIcon
            className="page-alert"
            message="无法读取沟通模板"
            description={templates.error.message}
            action={<Button onClick={() => void templates.refetch()}>重试</Button>}
          />
        )}

        <section className="panel-card message-template-toolbar">
          <Select
            aria-label="筛选模板状态"
            value={status}
            options={statusOptions}
            onChange={setStatus}
          />
          <Select
            aria-label="筛选模板类型"
            value={templateType ?? ''}
            options={templateTypeFilterOptions}
            onChange={(value) => setTemplateType(value ? (value as MessageTemplateType) : undefined)}
          />
          <Input.Search
            aria-label="搜索模板名称"
            allowClear
            placeholder="搜索模板名称"
            onSearch={setQuery}
          />
        </section>

        <section className="panel-card message-template-table-panel">
          <Table<MessageTemplateSummaryRecord>
            rowKey="id"
            loading={templates.isPending}
            dataSource={tableData}
            pagination={false}
            locale={{ emptyText: '暂无沟通模板' }}
            scroll={{ x: 920 }}
            columns={[
              {
                title: '模板',
                key: 'template',
                render: (_, template) => (
                  <Space direction="vertical" size={2}>
                    <Space size="small" wrap>
                      <Text strong>{template.name}</Text>
                      {statusTag(template.status)}
                    </Space>
                    <Text type="secondary">{template.current_subject}</Text>
                  </Space>
                ),
              },
              {
                title: '类型',
                dataIndex: 'template_type',
                width: 150,
                render: (value: MessageTemplateType) => templateTypeLabels[value],
              },
              {
                title: '版本',
                dataIndex: 'current_version_number',
                width: 100,
                render: (value: number) => <Tag color="blue">V{value}</Tag>,
              },
              {
                title: '更新时间',
                dataIndex: 'updated_at',
                width: 180,
                render: formatDateTime,
              },
              {
                title: '操作',
                key: 'actions',
                fixed: 'right',
                width: 260,
                render: (_, template) => (
                  <Space wrap>
                    <Button
                      icon={<EyeOutlined />}
                      onClick={() => setSelectedTemplateId(template.id)}
                    >
                      详情
                    </Button>
                    {template.allowed_actions.includes('create_version') && (
                      <Button
                        icon={<EditOutlined />}
                        onClick={() => {
                          setSelectedTemplateId(template.id)
                          void fetchMessageTemplate(template.id).then(openEdit)
                        }}
                      >
                        新版本
                      </Button>
                    )}
                    {(template.allowed_actions.includes('activate') ||
                      template.allowed_actions.includes('deactivate')) && (
                      <Button
                        danger={template.status === 'active'}
                        icon={<PoweroffOutlined />}
                        loading={statusMutation.isPending}
                        onClick={() => toggleStatus(template)}
                      >
                        {template.status === 'active' ? '停用' : '启用'}
                      </Button>
                    )}
                  </Space>
                ),
              },
            ]}
          />
        </section>
      </div>

      <Drawer
        title="模板详情"
        width={720}
        open={Boolean(selectedTemplateId)}
        onClose={() => setSelectedTemplateId(null)}
      >
        {selectedTemplate.isError && (
          <Alert type="error" showIcon message="无法读取模板详情" description={selectedTemplate.error.message} />
        )}
        {selectedTemplate.data && (
          <Space direction="vertical" size="large" className="message-template-detail">
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="模板名称">{selectedTemplate.data.name}</Descriptions.Item>
              <Descriptions.Item label="模板类型">
                {templateTypeLabels[selectedTemplate.data.template_type]}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                {statusTag(selectedTemplate.data.status)}
              </Descriptions.Item>
              <Descriptions.Item label="当前版本">
                V{selectedTemplate.data.current_version_number}
              </Descriptions.Item>
              <Descriptions.Item label="创建人">
                {selectedTemplate.data.created_by_display_name}
              </Descriptions.Item>
            </Descriptions>

            <div>
              <Title level={4}>当前版本内容</Title>
              <Paragraph strong>{selectedTemplate.data.current_version.subject}</Paragraph>
              <pre className="message-template-body-preview">
                {selectedTemplate.data.current_version.body}
              </pre>
              <Space size={[6, 6]} wrap>
                {selectedTemplate.data.current_version.variables.length ? (
                  selectedTemplate.data.current_version.variables.map((variable) => (
                    <Tag key={variable}>{`{{${variable}}}`}</Tag>
                  ))
                ) : (
                  <Text type="secondary">未配置变量</Text>
                )}
              </Space>
            </div>

            <div>
              <Title level={4}>版本历史</Title>
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={[...selectedTemplate.data.versions].reverse()}
                columns={[
                  {
                    title: '版本',
                    dataIndex: 'version_number',
                    width: 90,
                    render: (value: number) => <Tag color="blue">V{value}</Tag>,
                  },
                  { title: '主题', dataIndex: 'subject' },
                  {
                    title: '创建人',
                    dataIndex: 'created_by_display_name',
                    width: 120,
                  },
                  {
                    title: '创建时间',
                    dataIndex: 'created_at',
                    width: 180,
                    render: formatDateTime,
                  },
                ]}
              />
            </div>
          </Space>
        )}
      </Drawer>

      <Modal
        title="创建沟通模板"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => void createForm.submit()}
        confirmLoading={createMutation.isPending}
        destroyOnHidden
      >
        <TemplateForm form={createForm} mode="create" onFinish={submitCreate} />
      </Modal>

      <Modal
        title="保存为新版本"
        open={Boolean(editingTemplate)}
        onCancel={() => setEditingTemplate(null)}
        onOk={() => void editForm.submit()}
        confirmLoading={versionMutation.isPending}
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          className="message-template-version-alert"
          message="模板名称和类型保持不变，本次修改会生成新的历史版本。"
        />
        <TemplateForm form={editForm} mode="version" onFinish={submitVersion} />
      </Modal>
    </>
  )
}

function TemplateForm({
  form,
  mode,
  onFinish,
}: {
  form: ReturnType<typeof Form.useForm<TemplateFormValues>>[0]
  mode: 'create' | 'version'
  onFinish: (values: TemplateFormValues) => void
}) {
  return (
    <Form form={form} layout="vertical" onFinish={onFinish}>
      <Form.Item
        label="模板类型"
        name="templateType"
        rules={[{ required: true, message: '请选择模板类型' }]}
      >
        <Select disabled={mode === 'version'} options={templateTypeOptions} />
      </Form.Item>
      <Form.Item
        label="模板名称"
        name="name"
        rules={[{ required: true, message: '请输入模板名称' }]}
      >
        <Input disabled={mode === 'version'} maxLength={100} />
      </Form.Item>
      <Form.Item
        label="文案标题"
        name="subject"
        rules={[{ required: true, message: '请输入文案标题' }]}
      >
        <Input maxLength={100} placeholder="例如：面试通知 - {{job_title}}" />
      </Form.Item>
      <Form.Item
        label="文案正文"
        name="body"
        rules={[{ required: true, message: '请输入文案正文' }]}
      >
        <Input.TextArea
          rows={8}
          maxLength={5000}
          placeholder="使用 {{candidate_name}}、{{job_title}} 等变量生成可复制文案"
        />
      </Form.Item>
      <Form.Item label="变量清单" name="variablesText">
        <Input.TextArea
          rows={3}
          placeholder="每行一个变量，例如 candidate_name、job_title、interview_time"
        />
      </Form.Item>
      <Alert
        type="info"
        showIcon
        message="变量只能使用小写字母、数字和下划线；页面只模拟生成和复制，不连接短信、邮件或腾讯会议 API。"
      />
    </Form>
  )
}
