import {
  ArrowLeftOutlined,
  CloudUploadOutlined,
  DownloadOutlined,
  FileDoneOutlined,
  FileExcelOutlined,
  FileOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  List,
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
import { useNavigate, useParams } from 'react-router-dom'

import {
  ApiError,
  createScreeningBatch,
  fetchJob,
  fetchScreeningBatches,
  resumeFileUrl,
  retryResumeDocument,
  type BatchStatus,
  type ResumeDocumentRecord,
  type ScreeningBatchRecord,
} from '../api/client'

const { Title, Text } = Typography
const { Dragger } = Upload

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
  if (document.status === 'failed') return <Tag color="error">上传失败</Tag>
  if (document.status === 'processing') return <Tag color="processing">处理中</Tag>
  if (document.status === 'queued') return <Tag color="blue">等待处理</Tag>
  if (document.status === 'completed') return <Tag color="success">处理完成</Tag>
  return <Tag color="cyan">已安全保存</Tag>
}

function BatchCard({
  batch,
  jobId,
  archived,
}: {
  batch: ScreeningBatchRecord
  jobId: string
  archived: boolean
}) {
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const retryMutation = useMutation({
    mutationFn: ({ documentId, file }: { documentId: string; file: File }) =>
      retryResumeDocument(jobId, batch.id, documentId, file),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['batches', jobId] })
      messageApi.success('失败文件已重新上传')
    },
    onError: (error) =>
      messageApi.error(error instanceof ApiError ? error.message : '重新上传失败'),
  })
  const status = batchStatusMeta[batch.status]
  const completedPercent = batch.total_count
    ? Math.round((batch.success_count / batch.total_count) * 100)
    : 0

  return (
    <Card className="batch-card">
      {contextHolder}
      <div className="batch-card-heading">
        <div>
          <Space wrap>
            <Title level={4}>{batch.name}</Title>
            <Tag color={status.color}>{status.label}</Tag>
            <Tag>标准 V{batch.criteria_version_number}</Tag>
          </Space>
          <Text type="secondary">创建于 {formatDate(batch.created_at)}</Text>
        </div>
        <div className="batch-progress-summary">
          <Text type="secondary">安全接收进度</Text>
          <Progress percent={completedPercent} size="small" />
        </div>
      </div>

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
            actions={[
              document.status !== 'failed' ? (
                <Button
                  key="download"
                  type="link"
                  icon={<DownloadOutlined />}
                  href={resumeFileUrl(jobId, batch.id, document.id)}
                >
                  下载原文件
                </Button>
              ) : (
                <Upload
                  key="retry"
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
                </Upload>
              ),
            ]}
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
                  {documentStatus(document)}
                </Space>
              }
              description={
                <Space direction="vertical" size={2}>
                  <Text type="secondary">
                    {document.detected_type ? document.detected_type.toUpperCase() : '未识别'} ·{' '}
                    {formatSize(document.size_bytes)} · 第 {document.attempt_count} 次尝试
                  </Text>
                  {document.failure_message && (
                    <Text type="danger">{document.failure_message}</Text>
                  )}
                </Space>
              }
            />
          </List.Item>
        )}
      />
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
      ),
    onSuccess: async (batch) => {
      setFileList([])
      setBatchName('')
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
        <Space wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>
            返回职位列表
          </Button>
          <Button
            icon={<SettingOutlined />}
            onClick={() => navigate(`/jobs/${jobId}/criteria`)}
          >
            筛选标准
          </Button>
        </Space>
      </div>

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
              <div className="upload-policy-card">
                <FileOutlined />
                <div>
                  <Text strong>安全上传规则</Text>
                  <Text type="secondary">单批最多 50 份，单文件不超过 20 MB</Text>
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
                onChange={({ fileList: nextList }) => setFileList(nextList.slice(0, 50))}
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
                <Text type="secondary">已选择 {selectedFiles.length} / 50 份</Text>
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
              <BatchCard key={batch.id} batch={batch} jobId={jobId!} archived={archived} />
            ))}
          </div>
        )}
      </section>
    </>
  )
}
