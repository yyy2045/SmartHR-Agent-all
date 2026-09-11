import {
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
  Checkbox,
  Col,
  Collapse,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Table,
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
  fetchRecruitmentKnowledgeDocumentDetail,
  fetchRecruitmentKnowledgeDocuments,
  retrieveRecruitmentKnowledge,
  uploadRecruitmentKnowledgeDocument,
  type RecruitmentKnowledgeCategory,
  type RecruitmentKnowledgeChunkRecord,
  type RecruitmentKnowledgeDocumentListItem,
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

type RecruitmentKnowledgeParseEngine = 'pipeline' | 'vlm'

const parseEngineOptions: Array<{ value: RecruitmentKnowledgeParseEngine; label: string }> = [
  { value: 'pipeline', label: 'pipeline' },
  { value: 'vlm', label: 'vlm' },
]

const categoryLabelMap: Record<RecruitmentKnowledgeCategory, string> = {
  policy: '招聘制度',
  job_standard: '岗位标准',
  interview: '面试评分',
  offer: 'Offer 规则',
  compensation: '薪酬说明',
  communication: '沟通话术',
  general: '通用知识',
}

const visibilityLabelMap: Record<RecruitmentKnowledgeVisibilityScope, string> = {
  all_internal: '全体内部用户',
  recruiter_manager: '专员 + 用人经理',
  recruiter_only: '仅招聘专员',
  admin_only: '仅管理员',
}

const chunkStatusMeta: Record<
  RecruitmentKnowledgeChunkRecord['status'],
  { label: string; color: string }
> = {
  pending: { label: '待处理', color: 'default' },
  processing: { label: '处理中', color: 'processing' },
  completed: { label: '已索引', color: 'success' },
  failed: { label: '失败', color: 'error' },
}

function formatDateTime(value: string) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function renderDocumentChunkStatus(record: RecruitmentKnowledgeDocumentListItem) {
  if (!record.embedding_enabled) {
    return <Tag>未索引</Tag>
  }
  const processed = record.chunk_completed + record.chunk_failed
  const color = record.chunk_failed > 0 ? 'warning' : 'success'
  return (
    <Tag color={color}>
      {processed}/{record.chunk_count} 已处理
    </Tag>
  )
}

interface KnowledgeFormValues {
  title: string
  summary?: string
  category: RecruitmentKnowledgeCategory
  tags?: string[]
  visibilityScope: RecruitmentKnowledgeVisibilityScope
  changeNote: string
  rawText?: string
  forceOcr?: boolean
  parseEngine?: RecruitmentKnowledgeParseEngine
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
  const [documentFilter, setDocumentFilter] = useState<{
    category?: RecruitmentKnowledgeCategory | null
    q: string
  }>({ q: '' })
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null)

  const canMaintain = useMemo(
    () => auth.user?.roles.some((role) => ['administrator', 'recruiter'].includes(role)) ?? false,
    [auth.user?.roles],
  )

  const documents = useQuery({
    queryKey: ['recruitment-knowledge', 'documents', documentFilter],
    queryFn: () =>
      fetchRecruitmentKnowledgeDocuments({
        category: documentFilter.category ?? null,
        q: documentFilter.q || null,
        limit: 50,
        offset: 0,
      }),
    staleTime: 15_000,
  })

  const selectedDocument = useQuery({
    queryKey: ['recruitment-knowledge', 'documents', selectedDocumentId],
    queryFn: () => fetchRecruitmentKnowledgeDocumentDetail(selectedDocumentId!),
    enabled: Boolean(selectedDocumentId),
    staleTime: 15_000,
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
        forceOcr: values.forceOcr || undefined,
        parseEngine: values.parseEngine ?? 'pipeline',
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
              onClick={() => void documents.refetch()}
              loading={documents.isFetching}
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

        <Row gutter={[16, 16]}>
          <Col xs={24} xl={14}>
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

        <section className="panel-card recruitment-knowledge-documents">
          <Space direction="vertical" size="middle" className="full-width">
            <Space align="center" className="full-width" style={{ justifyContent: 'space-between' }}>
              <Space align="center">
                <FileTextOutlined />
                <Text strong>知识文档</Text>
                <Text type="secondary">
                  {documents.data ? `共 ${documents.data.total} 份` : ''}
                </Text>
              </Space>
              <Space wrap>
                <Select
                  allowClear
                  placeholder="按类别筛选"
                  style={{ width: 160 }}
                  options={categoryOptions}
                  value={documentFilter.category}
                  onChange={(value) =>
                    setDocumentFilter((prev) => ({ ...prev, category: value ?? null }))
                  }
                />
                <Input.Search
                  allowClear
                  placeholder="搜索标题"
                  style={{ width: 220 }}
                  onSearch={(value) => setDocumentFilter((prev) => ({ ...prev, q: value }))}
                />
                <Button
                  icon={<ReloadOutlined />}
                  onClick={() => void documents.refetch()}
                  loading={documents.isFetching}
                />
              </Space>
            </Space>

            <Table<RecruitmentKnowledgeDocumentListItem>
              rowKey="id"
              loading={documents.isPending}
              dataSource={documents.data?.items ?? []}
              pagination={false}
              locale={{ emptyText: <Empty description="暂无知识文档，请先录入或上传" /> }}
              onRow={(record) => ({
                onClick: () => setSelectedDocumentId(record.id),
                style: { cursor: 'pointer' },
              })}
              columns={[
                {
                  title: '标题',
                  key: 'title',
                  render: (_, record) => (
                    <Space direction="vertical" size={2}>
                      <Text strong>{record.title}</Text>
                      <Text type="secondary">{record.summary ?? '无摘要'}</Text>
                    </Space>
                  ),
                },
                {
                  title: '类别',
                  dataIndex: 'category',
                  width: 110,
                  render: (value: RecruitmentKnowledgeCategory) => categoryLabelMap[value],
                },
                {
                  title: '可见范围',
                  dataIndex: 'visibility_scope',
                  width: 140,
                  render: (value: RecruitmentKnowledgeVisibilityScope) => visibilityLabelMap[value],
                },
                {
                  title: '来源',
                  key: 'source',
                  width: 170,
                  render: (_, record) => (
                    <Space direction="vertical" size={2}>
                      <Tag color={record.current_source_type === 'upload' ? 'blue' : 'default'}>
                        {record.current_source_type === 'upload' ? '上传' : '手工'}
                      </Tag>
                      {record.current_source_filename && (
                        <Text type="secondary">{record.current_source_filename}</Text>
                      )}
                    </Space>
                  ),
                },
                {
                  title: '版本',
                  key: 'versions',
                  width: 90,
                  render: (_, record) => (
                    <Text>V{record.current_version_number ?? '—'} / {record.version_count}</Text>
                  ),
                },
                {
                  title: '分块',
                  key: 'chunks',
                  width: 140,
                  render: (_, record) => renderDocumentChunkStatus(record),
                },
                {
                  title: '更新时间',
                  dataIndex: 'updated_at',
                  width: 170,
                  render: formatDateTime,
                },
              ]}
            />
          </Space>
        </section>

        <Drawer
          title={selectedDocument.data?.title ?? '知识文档预览'}
          width={680}
          open={Boolean(selectedDocumentId)}
          onClose={() => setSelectedDocumentId(null)}
        >
          {selectedDocument.isPending && <Text type="secondary">正在加载文档…</Text>}
          {!selectedDocument.isPending && !selectedDocument.data && (
            <Alert
              type="error"
              showIcon
              message="无法读取文档详情"
              description={selectedDocument.error?.message}
            />
          )}
          {selectedDocument.data && (
            <Space direction="vertical" size="large" className="full-width">
              <Space wrap>
                <Tag>{categoryLabelMap[selectedDocument.data.category]}</Tag>
                <Tag>{visibilityLabelMap[selectedDocument.data.visibility_scope]}</Tag>
                <Tag
                  color={selectedDocument.data.source_type === 'upload' ? 'blue' : 'default'}
                >
                  {selectedDocument.data.source_type === 'upload' ? '上传' : '手工'}
                </Tag>
                {selectedDocument.data.source_filename && (
                  <Text type="secondary">{selectedDocument.data.source_filename}</Text>
                )}
                <Text type="secondary">版本 V{selectedDocument.data.current_version_number ?? '—'}</Text>
              </Space>
              {selectedDocument.data.summary && (
                <Paragraph type="secondary">{selectedDocument.data.summary}</Paragraph>
              )}
              {selectedDocument.data.parser_name && (
                <Text type="secondary">解析器：{selectedDocument.data.parser_name}</Text>
              )}
              <Collapse
                defaultActiveKey={['chunks']}
                items={[
                  {
                    key: 'chunks',
                    label: `分块预览（${selectedDocument.data.current_chunks.length}）`,
                    children: (
                      <Space direction="vertical" size="small" className="full-width">
                        {selectedDocument.data.current_chunks.length === 0 ? (
                          <Empty description="暂无分块" />
                        ) : (
                          selectedDocument.data.current_chunks.map((chunk) => (
                            <Card key={chunk.id} size="small" className="knowledge-chunk-card">
                              <Space direction="vertical" size={4} className="full-width">
                                <Space wrap>
                                  <Tag>#{chunk.chunk_index}</Tag>
                                  {chunk.heading_path.length > 0 && (
                                    <Text type="secondary">{chunk.heading_path.join(' / ')}</Text>
                                  )}
                                  {chunk.source_locator && (
                                    <Text type="secondary">{chunk.source_locator}</Text>
                                  )}
                                  <Tag color={chunkStatusMeta[chunk.status].color}>
                                    {chunkStatusMeta[chunk.status].label}
                                  </Tag>
                                </Space>
                                <Paragraph
                                  className="knowledge-chunk-text"
                                  style={{ whiteSpace: 'pre-wrap' }}
                                >
                                  {chunk.chunk_text}
                                </Paragraph>
                              </Space>
                            </Card>
                          ))
                        )}
                      </Space>
                    ),
                  },
                  {
                    key: 'raw',
                    label: '查看正文（raw_text）',
                    children: (
                      <Paragraph
                        className="knowledge-chunk-text"
                        style={{ whiteSpace: 'pre-wrap' }}
                      >
                        {selectedDocument.data.raw_text ?? '暂无正文'}
                      </Paragraph>
                    ),
                  },
                ]}
              />
            </Space>
          )}
        </Drawer>
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
        parseEngine: 'pipeline',
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
        <>
          <Row gutter={12}>
            <Col span={14}>
              <Form.Item name="parseEngine" label="解析引擎">
                <Select options={parseEngineOptions} />
              </Form.Item>
            </Col>
            <Col span={10}>
              <Form.Item name="forceOcr" label="强制 OCR" valuePropName="checked">
                <Checkbox>对扫描 PDF 启用 OCR</Checkbox>
              </Form.Item>
            </Col>
          </Row>
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
        </>
      )}
      <Button type="primary" htmlType="submit" icon={<FileTextOutlined />} loading={submitting}>
        {submitText}
      </Button>
    </Form>
  )
}

