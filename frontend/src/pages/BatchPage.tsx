import {
  CloudUploadOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
  FileDoneOutlined,
  FileExcelOutlined,
  FileOutlined,
  HistoryOutlined,
  RedoOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Input,
  List,
  Modal,
  Progress,
  Select,
  Skeleton,
  Space,
  Statistic,
  Tag,
  Typography,
  Upload,
  message,
  type UploadFile,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  ApiError,
  createScreeningBatch,
  deleteScreeningBatch,
  fetchJob,
  fetchResumeDocumentDetail,
  fetchScreeningBatches,
  reanalyzeBatch,
  resumeFileUrl,
  retryResumeDocument,
  retryResumeParsing,
  type BatchReanalysisRecord,
  type BatchStatus,
  type AIInputMode,
  type CriteriaVersion,
  type ResumeDocumentRecord,
  type ScreeningBatchRecord,
} from '../api/client'
import { ScreeningModuleNav } from '../components/ScreeningModuleNav'

const { Title, Text } = Typography
const { Dragger } = Upload
const MAX_BATCH_FILE_COUNT = 50

const batchStatusMeta: Record<BatchStatus, { color: string; label: string }> = {
  uploading: { color: 'processing', label: '上传中' },
  ready: { color: 'success', label: '已就绪' },
  partial_failure: { color: 'warning', label: '部分失败' },
  failed: { color: 'error', label: '全部失败' },
  processing: { color: 'processing', label: '处理中' },
  completed: { color: 'success', label: '已完成' },
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function documentStatus(document: ResumeDocumentRecord) {
  if (document.status === 'failed') {
    return <Tag color="error">{document.has_original_file ? '解析失败' : '上传失败'}</Tag>
  }
  if (document.status === 'processing') return <Tag color="processing">处理中</Tag>
  if (document.status === 'queued') return <Tag color="blue">等待解析</Tag>
  if (document.status === 'completed') return <Tag color="success">解析完成</Tag>
  return <Tag color="cyan">已安全保存</Tag>
}

const extractionMethodLabels: Record<string, string> = {
  pdf_text: 'PDF 文本提取',
  pdf_ocr: 'PDF OCR',
  docx_text: 'DOCX 文本提取',
  image_ocr: '图片 OCR',
}

function extractionMethodLabel(method: string | null) {
  if (!method) return '尚未解析'
  return extractionMethodLabels[method] ?? method
}

function segmentLocation(
  sourceType: 'pdf_page' | 'docx_paragraph' | 'image_ocr',
  pageNumber: number | null,
  paragraphIndex: number | null,
) {
  if (sourceType === 'pdf_page') return `PDF 第 ${pageNumber ?? '-'} 页`
  if (sourceType === 'docx_paragraph') return `DOCX 第 ${paragraphIndex ?? '-'} 段`
  return '图片 OCR'
}

function BatchCard({
  batch,
  jobId,
  archived,
  criteriaVersions,
}: {
  batch: ScreeningBatchRecord
  jobId: string
  archived: boolean
  criteriaVersions: CriteriaVersion[]
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>()
  const [reanalysisOpen, setReanalysisOpen] = useState(false)
  const [reanalysisCriteriaVersionId, setReanalysisCriteriaVersionId] = useState<string>()
  const [lastReanalysis, setLastReanalysis] = useState<BatchReanalysisRecord>()
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteConfirmation, setDeleteConfirmation] = useState('')
  const retryMutation = useMutation({
    mutationFn: ({ documentId, file }: { documentId: string; file: File }) =>
      retryResumeDocument(jobId, batch.id, documentId, file),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['batches', jobId] })
      messageApi.success('文件已重新上传并进入解析队列')
    },
    onError: (error) =>
      messageApi.error(error instanceof ApiError ? error.message : '重新上传失败'),
  })
  const parseRetryMutation = useMutation({
    mutationFn: (documentId: string) =>
      retryResumeParsing(jobId, batch.id, documentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['batches', jobId] })
      messageApi.success('文件已重新进入解析队列')
    },
    onError: (error) =>
      messageApi.error(error instanceof ApiError ? error.message : '重新处理失败'),
  })
  const reanalysisMutation = useMutation({
    mutationFn: (criteriaVersionId: string) =>
      reanalyzeBatch(jobId, batch.id, criteriaVersionId),
    onSuccess: async (response) => {
      setReanalysisOpen(false)
      setLastReanalysis(response)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['batches', jobId] }),
        queryClient.invalidateQueries({ queryKey: ['screening-results', jobId] }),
      ])
      if (response.status === 'queued') {
        messageApi.success(
          `整批分析 V${response.analysis_version} 已排队，共 ${response.queued_count} 份`,
        )
      } else {
        messageApi.warning(
          `整批分析已创建：排队 ${response.queued_count}，失败 ${response.failed_count}，跳过 ${response.skipped_count}`,
        )
      }
    },
    onError: (error) =>
      messageApi.error(error instanceof ApiError ? error.message : '整批重新分析失败'),
  })
  const deleteMutation = useMutation({
    mutationFn: () => deleteScreeningBatch(jobId, batch.id, deleteConfirmation),
    onSuccess: async (response) => {
      setDeleteOpen(false)
      setDeleteConfirmation('')
      if (response.status === 'cleanup_pending') {
        messageApi.warning(response.message ?? '批次已删除，私有暂存文件等待继续清理')
      } else {
        messageApi.success(
          `批次已永久删除，共清理 ${response.deleted_document_count} 份简历`,
        )
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['batches', jobId] }),
        queryClient.invalidateQueries({ queryKey: ['screening-results', jobId] }),
      ])
    },
    onError: (error) =>
      messageApi.error(error instanceof ApiError ? error.message : '永久删除批次失败'),
  })
  const detail = useQuery({
    queryKey: ['resume-document', jobId, batch.id, selectedDocumentId],
    queryFn: () =>
      fetchResumeDocumentDetail(jobId, batch.id, selectedDocumentId!),
    enabled: Boolean(selectedDocumentId),
  })
  const status = batchStatusMeta[batch.status]
  const processedPercent = batch.total_count
    ? Math.round(((batch.success_count + batch.failed_count) / batch.total_count) * 100)
    : 0
  const selectedDocument = batch.documents.find(
    (document) => document.id === selectedDocumentId,
  )

  const documentActions = (document: ResumeDocumentRecord): ReactNode[] => {
    const actions: ReactNode[] = []
    if (document.status === 'completed') {
      actions.push(
        <Button
          key="detail"
          type="link"
          icon={<EyeOutlined />}
          onClick={() => setSelectedDocumentId(document.id)}
        >
          查看文本
        </Button>,
      )
      actions.push(
        <Button
          key="history"
          type="link"
          icon={<HistoryOutlined />}
          onClick={() =>
            navigate(
              `/jobs/${jobId}/batches/${batch.id}/documents/${document.id}/history`,
            )
          }
        >
          资料与版本
        </Button>,
      )
    }
    if (document.status === 'failed' && document.has_original_file) {
      actions.push(
        <Button
          key="parse-retry"
          type="link"
          icon={<RedoOutlined />}
          disabled={archived}
          loading={parseRetryMutation.isPending}
          onClick={() => parseRetryMutation.mutate(document.id)}
        >
          重新处理
        </Button>,
      )
    }
    if (document.status === 'failed' && !document.has_original_file) {
      actions.push(
        <Upload
          key="upload-retry"
          accept=".pdf,.docx,.jpg,.jpeg,.png"
          maxCount={1}
          showUploadList={false}
          disabled={archived || retryMutation.isPending}
          beforeUpload={(file) => {
            retryMutation.mutate({ documentId: document.id, file })
            return Upload.LIST_IGNORE
          }}
        >
          <Button
            type="link"
            icon={<ReloadOutlined />}
            loading={retryMutation.isPending}
          >
            重新选择文件
          </Button>
        </Upload>,
      )
    }
    if (document.has_original_file) {
      actions.push(
        <Button
          key="download"
          type="link"
          icon={<DownloadOutlined />}
          href={resumeFileUrl(jobId, batch.id, document.id)}
        >
          下载原文件
        </Button>,
      )
    }
    return actions
  }

  return (
    <Card className="batch-card">
      {contextHolder}
      <div className="batch-card-heading">
        <div>
          <Space wrap>
            <Title level={4}>{batch.name}</Title>
            <Tag color={status.color}>{status.label}</Tag>
            <Tag>标准 V{batch.criteria_version_number}</Tag>
            <Tag color={batch.ai_input_mode === 'raw' ? 'orange' : 'blue'}>
              {batch.ai_input_mode === 'raw' ? '原文发送' : '脱敏后发送'}
            </Tag>
          </Space>
          <Text type="secondary">创建于 {formatDate(batch.created_at)}</Text>
        </div>
        <div className="batch-card-actions">
          <div className="batch-progress-summary">
            <Text type="secondary">批次处理进度</Text>
            <Progress percent={processedPercent} size="small" />
          </div>
          <Button
            icon={<ReloadOutlined />}
            disabled={
              archived ||
              !batch.documents.some(
                (document) => document.status === 'completed' && document.redacted_at,
              )
            }
            onClick={() => {
              setReanalysisCriteriaVersionId(criteriaVersions[0]?.id)
              setReanalysisOpen(true)
            }}
          >
            整批重新分析
          </Button>
          <Button
            danger
            icon={<DeleteOutlined />}
            onClick={() => setDeleteOpen(true)}
          >
            永久删除
          </Button>
        </div>
      </div>

      {lastReanalysis && (
        <Alert
          className="batch-reanalysis-result"
          type={lastReanalysis.status === 'queued' ? 'success' : 'warning'}
          showIcon
          message={`分析 V${lastReanalysis.analysis_version} 已创建`}
          description={`排队 ${lastReanalysis.queued_count} 份，创建失败 ${lastReanalysis.failed_count} 份，跳过 ${lastReanalysis.skipped_count} 份。所有旧分析结果继续保留。`}
        />
      )}

      <div className="batch-stat-grid">
        <Statistic title="文件总数" value={batch.total_count} />
        <Statistic title="成功" value={batch.success_count} valueStyle={{ color: '#168a60' }} />
        <Statistic title="失败" value={batch.failed_count} valueStyle={{ color: '#d04444' }} />
        <Statistic title="处理中" value={batch.processing_count} valueStyle={{ color: '#2477d4' }} />
      </div>

      <List
        className="document-list"
        dataSource={batch.documents}
        locale={{ emptyText: '批次中没有文件' }}
        renderItem={(document) => (
          <List.Item
            actions={documentActions(document)}
          >
            <List.Item.Meta
              avatar={
                <span className={`document-icon ${document.status === 'failed' ? 'is-error' : ''}`}>
                  {document.status === 'failed' ? <FileExcelOutlined /> : <FileDoneOutlined />}
                </span>
              }
              title={
                <Space wrap size="small">
                  <Text strong>{document.original_filename}</Text>
                  <Tag>{document.candidate_code}</Tag>
                  {documentStatus(document)}
                </Space>
              }
              description={
                <Space direction="vertical" size={2}>
                  <Text type="secondary">
                    {document.detected_type ? document.detected_type.toUpperCase() : '未识别'} ·{' '}
                    {formatSize(document.size_bytes)} · 第 {document.attempt_count} 次尝试
                  </Text>
                  {document.status === 'completed' && (
                    <Text type="secondary">
                      {extractionMethodLabel(document.extraction_method)} · {document.segment_count}{' '}
                      个片段 · {document.text_character_count} 个字符 · 已脱敏{' '}
                      {document.redaction_count} 项
                    </Text>
                  )}
                  {document.processing_attempt_count > 0 && document.status !== 'completed' && (
                    <Text type="secondary">
                      已进行 {document.processing_attempt_count} 次解析
                    </Text>
                  )}
                  {document.failure_message && (
                    <Text type="danger">{document.failure_message}</Text>
                  )}
                </Space>
              }
            />
          </List.Item>
        )}
      />

      <Drawer
        className="resume-text-drawer"
        width={720}
        open={Boolean(selectedDocumentId)}
        title={selectedDocument ? `解析文本 · ${selectedDocument.original_filename}` : '解析文本'}
        onClose={() => setSelectedDocumentId(undefined)}
      >
        {detail.isPending && <Skeleton active paragraph={{ rows: 10 }} />}
        {detail.isError && (
          <Alert
            type="error"
            showIcon
            message="无法读取解析文本"
            description={detail.error.message}
            action={<Button onClick={() => void detail.refetch()}>重试</Button>}
          />
        )}
        {detail.isSuccess && (
          <>
            <Descriptions
              className="resume-text-summary"
              size="small"
              column={2}
              items={[
                {
                  key: 'candidate-code',
                  label: '候选人编号',
                  children: detail.data.candidate_code,
                },
                {
                  key: 'method',
                  label: '解析方式',
                  children: extractionMethodLabel(detail.data.extraction_method),
                },
                { key: 'segments', label: '片段数', children: detail.data.segment_count },
                {
                  key: 'characters',
                  label: '字符数',
                  children: detail.data.text_character_count,
                },
                {
                  key: 'redactions',
                  label: '脱敏命中',
                  children: `${detail.data.redaction_count} 项`,
                },
                {
                  key: 'parsed-at',
                  label: '完成时间',
                  children: detail.data.parsed_at ? formatDate(detail.data.parsed_at) : '-',
                },
              ]}
            />
            <List
              className="resume-segment-list"
              dataSource={detail.data.text_segments}
              locale={{ emptyText: '没有可展示的文本片段' }}
              renderItem={(segment) => (
                <List.Item>
                  <article className="resume-segment-card">
                    <div className="resume-segment-heading">
                      <Space wrap size="small">
                        <Tag color="blue">{segment.segment_key}</Tag>
                        <Text strong>
                          {segmentLocation(
                            segment.source_type,
                            segment.page_number,
                            segment.paragraph_index,
                          )}
                        </Text>
                      </Space>
                      {segment.ocr_confidence !== null && (
                        <Text type="secondary">
                          OCR 置信度 {(segment.ocr_confidence * 100).toFixed(1)}%
                        </Text>
                      )}
                    </div>
                    <Text type="secondary">发送给外部模型的文本</Text>
                    <pre>{segment.redacted_text ?? segment.normalized_text}</pre>
                    <details className="resume-original-evidence">
                      <summary>查看授权原文证据</summary>
                      <pre>{segment.normalized_text}</pre>
                    </details>
                  </article>
                </List.Item>
              )}
            />
          </>
        )}
      </Drawer>

      <Modal
        title={`整批重新分析 · ${batch.name}`}
        open={reanalysisOpen}
        okText="确认整批重跑"
        cancelText="取消"
        confirmLoading={reanalysisMutation.isPending}
        okButtonProps={{ disabled: !reanalysisCriteriaVersionId }}
        onOk={() =>
          reanalysisCriteriaVersionId &&
          reanalysisMutation.mutate(reanalysisCriteriaVersionId)
        }
        onCancel={() => setReanalysisOpen(false)}
      >
        <Space direction="vertical" size="middle" className="full-width-space">
          <Alert
            type="info"
            showIcon
            message="本次重跑会为整个批次创建统一的分析版本"
            description="仅处理已完成解析和脱敏的简历；未就绪文件会跳过，历史档案与分析结果不会被覆盖。"
          />
          <div>
            <label htmlFor={`batch-reanalysis-criteria-${batch.id}`}>职位标准版本</label>
            <Select
              id={`batch-reanalysis-criteria-${batch.id}`}
              className="batch-reanalysis-select"
              value={reanalysisCriteriaVersionId}
              onChange={setReanalysisCriteriaVersionId}
              options={criteriaVersions.map((version) => ({
                value: version.id,
                label: `标准 V${version.version_number} · 通过线 ${version.pass_threshold}`,
              }))}
            />
          </div>
        </Space>
      </Modal>

      <Modal
        title={`永久删除批次 · ${batch.name}`}
        open={deleteOpen}
        okText="确认永久删除"
        okButtonProps={{
          danger: true,
          disabled: deleteConfirmation !== '永久删除',
        }}
        cancelText="取消"
        confirmLoading={deleteMutation.isPending}
        onOk={() => deleteMutation.mutate()}
        onCancel={() => {
          setDeleteOpen(false)
          setDeleteConfirmation('')
        }}
      >
        <Space direction="vertical" size="middle" className="full-width-space">
          <Alert
            type="error"
            showIcon
            message="该操作不可撤销"
            description={`将永久删除批次中的 ${batch.total_count} 份原始文件、解析文本、脱敏记录、候选人档案、分析结果和人工决策。`}
          />
          <div>
            <label htmlFor={`batch-delete-confirmation-${batch.id}`}>
              请输入“永久删除”确认操作
            </label>
            <Input
              id={`batch-delete-confirmation-${batch.id}`}
              value={deleteConfirmation}
              autoComplete="off"
              placeholder="永久删除"
              onChange={(event) => setDeleteConfirmation(event.target.value)}
            />
          </div>
        </Space>
      </Modal>
    </Card>
  )
}

export function BatchPage() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [batchName, setBatchName] = useState('')
  const [aiInputMode, setAIInputMode] = useState<AIInputMode>('raw')
  const [criteriaVersionId, setCriteriaVersionId] = useState<string>()
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
  })
  const batches = useQuery({
    queryKey: ['batches', jobId],
    queryFn: () => fetchScreeningBatches(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (query) =>
      query.state.data?.some((batch) => batch.status === 'processing') ? 3000 : false,
  })
  const confirmedVersions = useMemo(
    () =>
      [...(job.data?.criteria_versions ?? [])]
        .filter((version) => version.status === 'confirmed')
        .sort((left, right) => right.version_number - left.version_number),
    [job.data?.criteria_versions],
  )
  const uploadMutation = useMutation({
    mutationFn: () =>
      createScreeningBatch(
        jobId!,
        criteriaVersionId!,
        fileList.flatMap((item) => (item.originFileObj ? [item.originFileObj] : [])),
        batchName,
        aiInputMode,
      ),
    onSuccess: async (batch) => {
      setFileList([])
      setBatchName('')
      setAIInputMode('raw')
      await queryClient.invalidateQueries({ queryKey: ['batches', jobId] })
      if (batch.failed_count) {
        messageApi.warning(`批次已创建，其中 ${batch.failed_count} 个文件需要处理`)
      } else {
        messageApi.success('简历批次上传成功')
      }
    },
    onError: (error) =>
      messageApi.error(error instanceof ApiError ? error.message : '上传简历批次失败'),
  })

  useEffect(() => {
    if (!criteriaVersionId && confirmedVersions.length) {
      setCriteriaVersionId(confirmedVersions[0].id)
    }
  }, [confirmedVersions, criteriaVersionId])

  if (job.isPending || batches.isPending) {
    return <Skeleton active paragraph={{ rows: 12 }} />
  }

  if (job.isError || !job.data) {
    return (
      <Alert
        type="error"
        showIcon
        message="无法读取职位"
        description={job.error?.message}
        action={<Button onClick={() => void job.refetch()}>重试</Button>}
      />
    )
  }

  const archived = job.data.status === 'archived'
  const selectedFiles = fileList.flatMap((item) => (item.originFileObj ? [item.originFileObj] : []))

  return (
    <>
      {contextHolder}
      <div className="page-heading">
        <div>
          <Space wrap size="small">
            <Title level={2}>{job.data.title}</Title>
            {archived && <Tag>已归档</Tag>}
          </Space>
          <Text type="secondary">批量接收简历，并逐文件跟踪安全校验与处理状态</Text>
        </div>
      </div>

      <ScreeningModuleNav jobId={jobId} activeKey="batches" />

      {archived && (
        <Alert
          type="warning"
          showIcon
          message="该职位已归档，历史批次可查看，但不能继续上传或重试"
          className="page-alert"
        />
      )}

      <Card className="upload-panel" title="新建简历批次">
        {confirmedVersions.length === 0 ? (
          <Empty
            image={<SafetyCertificateOutlined className="empty-icon" />}
            description="上传简历前，需要先确认一版筛选标准"
          >
            <Button type="primary" onClick={() => navigate(`/jobs/${jobId}/criteria`)}>
              前往配置筛选标准
            </Button>
          </Empty>
        ) : (
          <div className="upload-panel-layout">
            <div className="upload-settings">
              <label htmlFor="criteria-version">筛选标准版本</label>
              <Select
                id="criteria-version"
                value={criteriaVersionId}
                onChange={setCriteriaVersionId}
                options={confirmedVersions.map((version) => ({
                  label: `V${version.version_number} · 已确认`,
                  value: version.id,
                }))}
                disabled={archived}
              />
              <label htmlFor="batch-name">批次名称</label>
              <Input
                id="batch-name"
                value={batchName}
                maxLength={200}
                placeholder="例如：7 月校招第一批"
                disabled={archived}
                onChange={(event) => setBatchName(event.target.value)}
              />
              <label htmlFor="ai-input-mode">AI 输入方式</label>
              <Select
                id="ai-input-mode"
                value={aiInputMode}
                onChange={setAIInputMode}
                disabled={archived}
                options={[
                  {
                    value: 'raw',
                    label: '发送原文（默认）',
                  },
                  {
                    value: 'redacted',
                    label: '脱敏后发送',
                  },
                ]}
              />
              <Text type="secondary">
                {aiInputMode === 'raw'
                  ? 'AI 将接收解析后的简历原文，可能包含个人信息。'
                  : 'AI 仅接收本地脱敏后的文本；发现残留敏感信息时会停止分析。'}
              </Text>
              <div className="upload-policy-card">
                <FileOutlined />
                <div>
                  <Text strong>安全上传规则</Text>
                  <Text type="secondary">
                    单批最多 {MAX_BATCH_FILE_COUNT} 份，单文件不超过 20 MB
                  </Text>
                  <Text type="secondary">支持 PDF、DOCX、JPG、PNG</Text>
                </div>
              </div>
            </div>

            <div className="upload-dropzone">
              <Dragger
                multiple
                accept=".pdf,.docx,.jpg,.jpeg,.png"
                fileList={fileList}
                disabled={archived || uploadMutation.isPending}
                beforeUpload={() => false}
                onChange={({ fileList: nextList }) =>
                  setFileList(nextList.slice(0, MAX_BATCH_FILE_COUNT))
                }
                onRemove={(file) => {
                  setFileList((current) => current.filter((item) => item.uid !== file.uid))
                  return true
                }}
              >
                <p className="ant-upload-drag-icon">
                  <CloudUploadOutlined />
                </p>
                <p className="ant-upload-text">拖拽简历到这里，或点击选择文件</p>
                <p className="ant-upload-hint">系统会逐文件校验，单个失败不会影响整个批次</p>
              </Dragger>
              <div className="upload-submit-row">
                <Text type="secondary">
                  已选择 {selectedFiles.length} / {MAX_BATCH_FILE_COUNT} 份
                </Text>
                <Button
                  type="primary"
                  icon={<CloudUploadOutlined />}
                  loading={uploadMutation.isPending}
                  disabled={archived || !criteriaVersionId || selectedFiles.length === 0}
                  onClick={() => uploadMutation.mutate()}
                >
                  开始上传
                </Button>
              </div>
            </div>
          </div>
        )}
      </Card>

      <section className="batch-history" aria-label="简历批次历史">
        <div className="section-heading">
          <div>
            <Title level={3}>批次记录</Title>
            <Text type="secondary">查看每批简历的成功、失败与处理中数量</Text>
          </div>
          <Button icon={<ReloadOutlined />} onClick={() => void batches.refetch()}>
            刷新状态
          </Button>
        </div>

        {batches.isError && (
          <Alert
            type="error"
            showIcon
            message="无法读取简历批次"
            description={batches.error.message}
          />
        )}
        {batches.isSuccess && batches.data.length === 0 && (
          <div className="empty-workspace batch-empty">
            <Empty description="还没有简历批次" />
          </div>
        )}
        {batches.isSuccess && batches.data.length > 0 && (
          <div className="batch-list">
            {batches.data.map((batch) => (
              <BatchCard
                key={batch.id}
                batch={batch}
                jobId={jobId!}
                archived={archived}
                criteriaVersions={confirmedVersions}
              />
            ))}
          </div>
        )}
      </section>
    </>
  )
}
