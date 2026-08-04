import {
  DatabaseOutlined,
  FileTextOutlined,
  ReloadOutlined,
  SearchOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
  type UploadFile,
} from 'antd'
import { useMemo, useState } from 'react'

import {
  ApiError,
  createRecruitmentKnowledgeManual,
  fetchRecruitmentKnowledgeBases,
  retrieveRecruitmentKnowledge,
  uploadRecruitmentKnowledgeDocument,
  type RecruitmentKnowledgeCategory,
  type RecruitmentKnowledgeRetrievalRecord,
  type RecruitmentKnowledgeVisibilityScope,
} from '../api/client'
import { useAuth } from '../auth/context'

const { Text, Title, Paragraph } = Typography
const { TextArea } = Input

const categoryOptions: Array<{ value: RecruitmentKnowledgeCategory; label: string }> = [
  { value: 'policy', label: '招聘制度' },
  { value: 'job_standard', label: '岗位标准' },
  { value: 'interview', label: '面试评分' },
  { value: 'offer', label: 'Offer 规则' },
  { value: 'compensation', label: '薪酬说明' },
  { value: 'communication', label: '沟通话术' },
  { value: 'general', label: '通用知识' },
]

const visibilityOptions: Array<{ value: RecruitmentKnowledgeVisibilityScope; label: string }> = [
  { value: 'all_internal', label: '全体内部用户' },
  { value: 'recruiter_manager', label: '招聘专员 + 用人经理' },
  { value: 'recruiter_only', label: '仅招聘专员' },
  { value: 'admin_only', label: '仅管理员' },
]

interface KnowledgeFormValues {
  title: string
  summary?: string
  category: RecruitmentKnowledgeCategory
  tags?: string[]
  visibilityScope: RecruitmentKnowledgeVisibilityScope
  changeNote: string
  rawText?: string
}

interface RetrievalFormValues {
  query: string
  category?: RecruitmentKnowledgeCategory
  tags?: string[]
  limit: number
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback
}

export function RecruitmentKnowledgePage() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [manualForm] = Form.useForm<KnowledgeFormValues>()
  const [uploadForm] = Form.useForm<KnowledgeFormValues>()
  const [retrievalForm] = Form.useForm<RetrievalFormValues>()
  const [uploadFiles, setUploadFiles] = useState<UploadFile[]>([])
  const [retrievalResult, setRetrievalResult] =
    useState<RecruitmentKnowledgeRetrievalRecord | null>(null)

  const canMaintain = useMemo(
    () => auth.user?.roles.some((role) => ['administrator', 'recruiter'].includes(role)) ?? false,
    [auth.user?.roles],
  )

  const bases = useQuery({
    queryKey: ['recruitment-knowledge', 'bases'],
    queryFn: fetchRecruitmentKnowledgeBases,
    staleTime: 30_000,
  })

  const manualMutation = useMutation({
    mutationFn: (values: KnowledgeFormValues) =>
      createRecruitmentKnowledgeManual({
        title: values.title,
        summary: values.summary?.trim() || null,
        category: values.category,
        tags: values.tags ?? [],
        visibilityScope: values.visibilityScope,
        changeNote: values.changeNote,
        rawText: values.rawText ?? '',
      }),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['recruitment-knowledge'] })
      manualForm.resetFields()
      messageApi.success(
        result.index_task_id
          ? '知识文档已保存，索引任务已创建'
          : '知识文档已保存，Embedding 未开启时可稍后重建索引',
      )
    },
  })

  const uploadMutation = useMutation({
    mutationFn: (values: KnowledgeFormValues) => {
      const file = uploadFiles[0]?.originFileObj
      if (!file) throw new Error('请选择要上传的知识文档')
      return uploadRecruitmentKnowledgeDocument({
        title: values.title,
        summary: values.summary?.trim() || null,
        category: values.category,
        tags: values.tags ?? [],
        visibilityScope: values.visibilityScope,
        changeNote: values.changeNote,
        file,
      })
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['recruitment-knowledge'] })
      uploadForm.resetFields()
      setUploadFiles([])
      messageApi.success(
        result.index_task_id
          ? '知识文档已上传，索引任务已创建'
          : '知识文档已上传，Embedding 未开启时可稍后重建索引',
      )
    },
  })

  const retrievalMutation = useMutation({
    mutationFn: (values: RetrievalFormValues) =>
      retrieveRecruitmentKnowledge({
        scenario: 'knowledge_preview',
        query: values.query,
        category: values.category ?? null,
        tags: values.tags ?? [],
        limit: values.limit,
      }),
    onSuccess: setRetrievalResult,
  })

  const mutationError = manualMutation.error ?? uploadMutation.error ?? retrievalMutation.error

  return (
    <>
      {contextHolder}
      <div className="recruitment-knowledge-page">
        <div className="page-heading">
          <div>
            <Title level={2}>企业知识库</Title>
            <Text type="secondary">
              维护招聘制度、岗位标准、面试评分、Offer 规则和沟通话术；AI 检索时返回可追溯引用。
            </Text>
          </div>
          <Space wrap>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => void bases.refetch()}
              loading={bases.isFetching}
            >
              刷新
            </Button>
          </Space>
        </div>

        {mutationError && (
          <Alert
            type="error"
            showIcon
            closable
            className="page-alert"
            message={errorMessage(mutationError, '企业知识库操作失败')}
          />
        )}

        {bases.isError && (
          <Alert
            type="error"
            showIcon
            className="page-alert"
            message="无法读取企业知识库"
            description={bases.error.message}
          />
        )}

        <Row gutter={[16, 16]}>
          <Col xs={24} xl={14}>
            <section className="panel-card">
              <Space direction="vertical" size="middle" className="full-width">
                <Space align="center">
                  <DatabaseOutlined />
                  <Text strong>知识库概览</Text>
                </Space>
                <Space wrap>
                  {(bases.data?.items ?? []).map((base) => (
                    <Tag key={base.id} color={base.status === 'active' ? 'green' : 'default'}>
                      {base.name}
                    </Tag>
                  ))}
                  {!bases.isPending && !bases.data?.items.length && <Text type="secondary">暂无知识库</Text>}
                </Space>
              </Space>
            </section>

            <section className="panel-card recruitment-knowledge-editor">
              <Tabs
                items={[
                  {
                    key: 'manual',
                    label: '手工录入',
                    disabled: !canMaintain,
                    children: (
                      <KnowledgeEditorForm
                        form={manualForm}
                        submitting={manualMutation.isPending}
                        submitText="保存知识文档"
                        includeRawText
                        onFinish={manualMutation.mutate}
                      />
                    ),
                  },
                  {
                    key: 'upload',
                    label: '上传文档',
                    disabled: !canMaintain,
                    children: (
                      <KnowledgeEditorForm
                        form={uploadForm}
                        submitting={uploadMutation.isPending}
                        submitText="上传并解析"
                        uploadFiles={uploadFiles}
                        onUploadFilesChange={setUploadFiles}
                        onFinish={uploadMutation.mutate}
                      />
                    ),
                  },
                ]}
              />
              {!canMaintain && (
                <Alert
                  showIcon
                  type="info"
                  message="当前角色仅可检索授权范围内知识，不能维护知识文档。"
                />
              )}
            </section>
          </Col>

          <Col xs={24} xl={10}>
            <section className="panel-card recruitment-knowledge-retrieval">
              <Space direction="vertical" size="middle" className="full-width">
                <div>
                  <Title level={4}>RAG 检索预览</Title>
                  <Text type="secondary">
                    用当前权限模拟 AI 上下文召回。权限不足的知识不会进入返回结果。
                  </Text>
                </div>
                <Form
                  form={retrievalForm}
                  layout="vertical"
                  initialValues={{ limit: 5 }}
                  onFinish={retrievalMutation.mutate}
                >
                  <Form.Item name="query" label="检索问题" rules={[{ required: true }]}>
                    <TextArea rows={4} placeholder="例如：Offer 审批前需要确认哪些信息？" />
                  </Form.Item>
                  <Row gutter={12}>
                    <Col span={14}>
                      <Form.Item name="category" label="类别">
                        <Select allowClear options={categoryOptions} />
                      </Form.Item>
                    </Col>
                    <Col span={10}>
                      <Form.Item name="limit" label="返回条数">
                        <InputNumber min={1} max={20} className="full-width" />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.Item name="tags" label="标签">
                    <Select mode="tags" tokenSeparators={[',', '，']} />
                  </Form.Item>
                  <Button
                    type="primary"
                    htmlType="submit"
                    icon={<SearchOutlined />}
                    loading={retrievalMutation.isPending}
                  >
                    检索知识库
                  </Button>
                </Form>

                {retrievalResult && (
                  <Space direction="vertical" size="small" className="full-width">
                    <Text type="secondary">
                      返回 {retrievalResult.returned_count} 条引用，权限过滤{' '}
                      {retrievalResult.filtered_count} 条
                    </Text>
                    {retrievalResult.citations.map((citation) => (
                      <Card key={citation.chunk_id} size="small" className="knowledge-citation-card">
                        <Space direction="vertical" size={4}>
                          <Space wrap>
                            <Tag color="blue">V{citation.version_number}</Tag>
                            <Text strong>{citation.document_title}</Text>
                            <Text type="secondary">相似度 {Math.round(citation.score * 100)}%</Text>
                          </Space>
                          {citation.heading_path.length > 0 && (
                            <Text type="secondary">{citation.heading_path.join(' / ')}</Text>
                          )}
                          <Paragraph>{citation.snippet}</Paragraph>
                          {citation.source_locator && (
                            <Text type="secondary">来源：{citation.source_locator}</Text>
                          )}
                        </Space>
                      </Card>
                    ))}
                    {retrievalResult.returned_count === 0 && (
                      <Alert type="info" showIcon message="没有检索到可见知识引用" />
                    )}
                  </Space>
                )}
              </Space>
            </section>
          </Col>
        </Row>
      </div>
    </>
  )
}

function KnowledgeEditorForm({
  form,
  submitting,
  submitText,
  includeRawText = false,
  uploadFiles,
  onUploadFilesChange,
  onFinish,
}: {
  form: ReturnType<typeof Form.useForm<KnowledgeFormValues>>[0]
  submitting: boolean
  submitText: string
  includeRawText?: boolean
  uploadFiles?: UploadFile[]
  onUploadFilesChange?: (files: UploadFile[]) => void
  onFinish: (values: KnowledgeFormValues) => void
}) {
  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={{
        category: 'policy',
        visibilityScope: 'all_internal',
      }}
      onFinish={onFinish}
    >
      <Form.Item name="title" label="文档标题" rules={[{ required: true }]}>
        <Input placeholder="例如：后端工程师面试评分标准" />
      </Form.Item>
      <Form.Item name="summary" label="摘要">
        <TextArea rows={2} />
      </Form.Item>
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item name="category" label="类别" rules={[{ required: true }]}>
            <Select options={categoryOptions} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="visibilityScope" label="可见范围" rules={[{ required: true }]}>
            <Select options={visibilityOptions} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="tags" label="标签">
        <Select mode="tags" tokenSeparators={[',', '，']} placeholder="输入后回车" />
      </Form.Item>
      <Form.Item name="changeNote" label="版本说明" rules={[{ required: true }]}>
        <Input placeholder="说明这版知识的来源或变更原因" />
      </Form.Item>
      {includeRawText ? (
        <Form.Item name="rawText" label="知识正文" rules={[{ required: true }]}>
          <TextArea rows={9} placeholder="# 面试评分标准&#10;候选人需要..." />
        </Form.Item>
      ) : (
        <Form.Item label="知识文件" required>
          <Upload
            beforeUpload={() => false}
            maxCount={1}
            fileList={uploadFiles}
            onChange={({ fileList }) => onUploadFilesChange?.(fileList)}
            accept=".txt,.md,.pdf,.docx"
          >
            <Button icon={<UploadOutlined />}>选择 TXT / Markdown / PDF / DOCX</Button>
          </Upload>
        </Form.Item>
      )}
      <Button type="primary" htmlType="submit" icon={<FileTextOutlined />} loading={submitting}>
        {submitText}
      </Button>
    </Form>
  )
}

