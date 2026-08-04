import {
  BranchesOutlined,
  CloudUploadOutlined,
  EyeOutlined,
  PlusOutlined,
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
import { useState } from 'react'

import {
  ApiError,
  createPromptTemplate,
  createPromptTemplateVersion,
  fetchPromptTemplate,
  fetchPromptTemplates,
  publishPromptTemplateVersion,
  type PromptScenario,
  type PromptTemplateContentInput,
  type PromptTemplateRecord,
  type PromptTemplateVersionRecord,
  type PromptVersionStatus,
} from '../api/client'

const { Text, Title, Paragraph } = Typography
const { TextArea } = Input

const scenarioLabels: Record<PromptScenario, string> = {
  jd_generation: 'JD 结构化',
  resume_analysis: '简历评分',
  resume_analysis_repair: '简历评分修复',
  interview_report: '面试报告',
  offer_copy: 'Offer 文案',
  candidate_comparison: '候选人对比',
  candidate_qa: '候选人问答',
}

const statusMeta: Record<PromptVersionStatus, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  published: { label: '已发布', color: 'success' },
  retired: { label: '历史版本', color: 'blue' },
}

interface PromptFormValues {
  scenario: PromptScenario
  name: string
  description?: string
  changeNote: string
  systemPrompt: string
  userPromptTemplate: string
  variablesText?: string
  outputSchemaText?: string
  modelParametersText?: string
}

function formatDateTime(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
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

function stringifyJson(value: Record<string, unknown> | null | undefined) {
  return value ? JSON.stringify(value, null, 2) : ''
}

function parseJsonObject(value: string | undefined, fallback: Record<string, unknown> | null) {
  const trimmed = value?.trim()
  if (!trimmed) return fallback
  const parsed = JSON.parse(trimmed) as unknown
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error('JSON 必须是对象')
  }
  return parsed as Record<string, unknown>
}

function currentPublishedVersion(template: PromptTemplateRecord) {
  return (
    template.versions.find((version) => version.status === 'published') ??
    template.versions.find((version) => version.version_number === template.current_version_number) ??
    null
  )
}

function promptError(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback
}

export function PromptTemplateManagementPage() {
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [createOpen, setCreateOpen] = useState(false)
  const [versionTarget, setVersionTarget] = useState<PromptTemplateRecord | null>(null)
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null)
  const [createForm] = Form.useForm<PromptFormValues>()
  const [versionForm] = Form.useForm<PromptFormValues>()

  const templates = useQuery({
    queryKey: ['prompt-templates'],
    queryFn: fetchPromptTemplates,
    staleTime: 15_000,
  })

  const selectedTemplate = useQuery({
    queryKey: ['prompt-template', selectedTemplateId],
    queryFn: () => fetchPromptTemplate(selectedTemplateId!),
    enabled: Boolean(selectedTemplateId),
  })

  async function invalidate(templateId?: string) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['prompt-templates'] }),
      templateId
        ? queryClient.invalidateQueries({ queryKey: ['prompt-template', templateId] })
        : Promise.resolve(),
    ])
  }

  function contentFromValues(values: PromptFormValues): PromptTemplateContentInput {
    return {
      changeNote: values.changeNote,
      systemPrompt: values.systemPrompt,
      userPromptTemplate: values.userPromptTemplate,
      variables: parseVariables(values.variablesText),
      outputSchema: parseJsonObject(values.outputSchemaText, null),
      modelParameters: parseJsonObject(values.modelParametersText, {}) ?? {},
    }
  }

  const createMutation = useMutation({
    mutationFn: (values: PromptFormValues) =>
      createPromptTemplate({
        scenario: values.scenario,
        name: values.name,
        description: values.description?.trim() || null,
        ...contentFromValues(values),
      }),
    onSuccess: async (template) => {
      await invalidate(template.id)
      setCreateOpen(false)
      createForm.resetFields()
      setSelectedTemplateId(template.id)
      messageApi.success('Prompt 模板草稿已创建')
    },
  })

  const versionMutation = useMutation({
    mutationFn: (values: PromptFormValues) => {
      if (!versionTarget) throw new Error('缺少目标模板')
      const sourceVersion = currentPublishedVersion(versionTarget)
      return createPromptTemplateVersion(versionTarget.id, {
        sourceVersionId: sourceVersion?.id ?? null,
        ...contentFromValues(values),
      })
    },
    onSuccess: async (template) => {
      await invalidate(template.id)
      setVersionTarget(null)
      versionForm.resetFields()
      setSelectedTemplateId(template.id)
      messageApi.success('Prompt 新版本草稿已保存')
    },
  })

  const publishMutation = useMutation({
    mutationFn: ({
      template,
      version,
    }: {
      template: PromptTemplateRecord
      version: PromptTemplateVersionRecord
    }) => publishPromptTemplateVersion(template.id, version.id, template.resource_version),
    onSuccess: async (template) => {
      await invalidate(template.id)
      messageApi.success(`已发布 V${template.current_version_number}`)
    },
  })

  const mutationError = createMutation.error ?? versionMutation.error ?? publishMutation.error

  function openVersionModal(template: PromptTemplateRecord) {
    const source = currentPublishedVersion(template)
    setVersionTarget(template)
    versionForm.setFieldsValue({
      changeNote: '',
      systemPrompt: source?.system_prompt ?? '',
      userPromptTemplate: source?.user_prompt_template ?? '',
      variablesText: source?.variables.join('\n') ?? '',
      outputSchemaText: stringifyJson(source?.output_schema),
      modelParametersText: stringifyJson(source?.model_parameters ?? {}),
    })
  }

  return (
    <>
      {contextHolder}
      <div className="prompt-template-page">
        <div className="page-heading">
          <div>
            <Title level={2}>PromptOps</Title>
            <Text type="secondary">
              维护场景化 Prompt 模板、输出 Schema 和发布版本；AI 调用会逐步绑定到具体版本。
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
              创建 Prompt
            </Button>
          </Space>
        </div>

        {mutationError && (
          <Alert
            type="error"
            showIcon
            closable
            className="page-alert"
            message={promptError(mutationError, 'Prompt 模板操作失败')}
          />
        )}

        {templates.isError && (
          <Alert
            type="error"
            showIcon
            className="page-alert"
            message="无法读取 Prompt 模板"
            description={templates.error.message}
            action={<Button onClick={() => void templates.refetch()}>重试</Button>}
          />
        )}

        <section className="panel-card prompt-template-table-panel">
          <Table<PromptTemplateRecord>
            rowKey="id"
            loading={templates.isPending}
            dataSource={templates.data?.items ?? []}
            pagination={false}
            locale={{ emptyText: '暂无 Prompt 模板' }}
            scroll={{ x: 980 }}
            columns={[
              {
                title: '模板',
                key: 'template',
                render: (_, template) => (
                  <Space direction="vertical" size={2}>
                    <Space size="small" wrap>
                      <Text strong>{template.name}</Text>
                      <Tag color="purple">{scenarioLabels[template.scenario]}</Tag>
                    </Space>
                    <Text type="secondary">{template.description ?? '未填写描述'}</Text>
                  </Space>
                ),
              },
              {
                title: '当前发布',
                key: 'current',
                width: 140,
                render: (_, template) =>
                  template.current_version_number ? (
                    <Tag color="success">V{template.current_version_number}</Tag>
                  ) : (
                    <Tag>未发布</Tag>
                  ),
              },
              {
                title: '版本数',
                key: 'versions',
                width: 100,
                render: (_, template) => template.versions.length,
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
                    <Button icon={<EyeOutlined />} onClick={() => setSelectedTemplateId(template.id)}>
                      详情
                    </Button>
                    <Button icon={<BranchesOutlined />} onClick={() => openVersionModal(template)}>
                      新版本
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        </section>
      </div>

      <Drawer
        title="Prompt 模板详情"
        width={760}
        open={Boolean(selectedTemplateId)}
        onClose={() => setSelectedTemplateId(null)}
      >
        {selectedTemplate.isError && (
          <Alert
            type="error"
            showIcon
            message="无法读取 Prompt 模板详情"
            description={selectedTemplate.error.message}
          />
        )}
        {selectedTemplate.data && (
          <Space direction="vertical" size="large" className="prompt-template-detail">
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="场景">
                {scenarioLabels[selectedTemplate.data.scenario]}
              </Descriptions.Item>
              <Descriptions.Item label="资源版本">
                {selectedTemplate.data.resource_version}
              </Descriptions.Item>
              <Descriptions.Item label="当前发布">
                {selectedTemplate.data.current_version_number
                  ? `V${selectedTemplate.data.current_version_number}`
                  : '未发布'}
              </Descriptions.Item>
            </Descriptions>

            <div>
              <Title level={4}>版本历史</Title>
              <Space direction="vertical" className="prompt-version-list">
                {selectedTemplate.data.versions.map((version) => (
                  <CardLikeVersion
                    key={version.id}
                    version={version}
                    template={selectedTemplate.data}
                    publishing={publishMutation.isPending}
                    onPublish={() =>
                      publishMutation.mutate({
                        template: selectedTemplate.data!,
                        version,
                      })
                    }
                  />
                ))}
              </Space>
            </div>
          </Space>
        )}
      </Drawer>

      <Modal
        title="创建 Prompt 模板"
        open={createOpen}
        okText="保存草稿"
        confirmLoading={createMutation.isPending}
        onCancel={() => setCreateOpen(false)}
        onOk={() => void createForm.submit()}
        width={820}
      >
        <PromptTemplateForm form={createForm} includeTemplateFields onFinish={createMutation.mutate} />
      </Modal>

      <Modal
        title={versionTarget ? `保存 ${versionTarget.name} 的新版本` : '保存新版本'}
        open={Boolean(versionTarget)}
        okText="保存新版本草稿"
        confirmLoading={versionMutation.isPending}
        onCancel={() => setVersionTarget(null)}
        onOk={() => void versionForm.submit()}
        width={820}
      >
        <PromptTemplateForm form={versionForm} onFinish={versionMutation.mutate} />
      </Modal>
    </>
  )
}

function CardLikeVersion({
  version,
  template,
  publishing,
  onPublish,
}: {
  version: PromptTemplateVersionRecord
  template: PromptTemplateRecord
  publishing: boolean
  onPublish: () => void
}) {
  const meta = statusMeta[version.status]
  const canPublish = version.status !== 'published'
  return (
    <div className="panel-card prompt-version-card">
      <Space align="start" className="prompt-version-card-heading">
        <div>
          <Space wrap>
            <Text strong>V{version.version_number}</Text>
            <Tag color={meta.color}>{meta.label}</Tag>
            {version.version_number === template.current_version_number && (
              <Tag color="success">当前使用</Tag>
            )}
          </Space>
          <Paragraph type="secondary">{version.change_note}</Paragraph>
        </div>
        {canPublish && (
          <Button
            icon={<CloudUploadOutlined />}
            loading={publishing}
            onClick={onPublish}
          >
            {version.status === 'retired' ? '回滚到此版本' : '发布'}
          </Button>
        )}
      </Space>
      <Descriptions bordered column={1} size="small">
        <Descriptions.Item label="创建人">{version.created_by_display_name}</Descriptions.Item>
        <Descriptions.Item label="发布时间">{formatDateTime(version.published_at)}</Descriptions.Item>
        <Descriptions.Item label="变量">
          {version.variables.length
            ? version.variables.map((item) => <Tag key={item}>{`{{${item}}}`}</Tag>)
            : '未配置变量'}
        </Descriptions.Item>
      </Descriptions>
      <Title level={5}>System Prompt</Title>
      <pre className="message-template-body-preview">{version.system_prompt}</pre>
      <Title level={5}>User Prompt Template</Title>
      <pre className="message-template-body-preview">{version.user_prompt_template}</pre>
    </div>
  )
}

function PromptTemplateForm({
  form,
  includeTemplateFields = false,
  onFinish,
}: {
  form: ReturnType<typeof Form.useForm<PromptFormValues>>[0]
  includeTemplateFields?: boolean
  onFinish: (values: PromptFormValues) => void
}) {
  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={{
        scenario: 'resume_analysis',
        modelParametersText: '{"temperature":0}',
      }}
      onFinish={onFinish}
    >
      {includeTemplateFields && (
        <>
          <Form.Item
            name="scenario"
            label="业务场景"
            rules={[{ required: true, message: '请选择业务场景' }]}
          >
            <Select
              options={Object.entries(scenarioLabels).map(([value, label]) => ({
                value,
                label,
              }))}
            />
          </Form.Item>
          <Form.Item name="name" label="模板名称" rules={[{ required: true }]}>
            <Input placeholder="例如：简历评分 Prompt" />
          </Form.Item>
          <Form.Item name="description" label="模板说明">
            <TextArea rows={2} />
          </Form.Item>
        </>
      )}
      <Form.Item name="changeNote" label="版本说明" rules={[{ required: true }]}>
        <Input placeholder="说明这版 Prompt 为什么修改" />
      </Form.Item>
      <Form.Item name="systemPrompt" label="System Prompt" rules={[{ required: true }]}>
        <TextArea rows={5} />
      </Form.Item>
      <Form.Item name="userPromptTemplate" label="User Prompt 模板" rules={[{ required: true }]}>
        <TextArea rows={5} />
      </Form.Item>
      <Form.Item name="variablesText" label="变量，一行一个">
        <TextArea rows={3} placeholder="criteria&#10;resume" />
      </Form.Item>
      <Form.Item name="outputSchemaText" label="JSON Schema，可选">
        <TextArea rows={4} placeholder='{"type":"object"}' />
      </Form.Item>
      <Form.Item name="modelParametersText" label="模型参数 JSON，可选">
        <TextArea rows={3} placeholder='{"temperature":0}' />
      </Form.Item>
    </Form>
  )
}
