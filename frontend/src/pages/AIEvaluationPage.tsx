import {
  CheckCircleOutlined,
  ExperimentOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import { useMemo, useState } from 'react'

import {
  createDefaultResumeEvaluationDataset,
  fetchAIEvaluationDatasets,
  fetchAIEvaluationErrorCases,
  fetchAIEvaluationRun,
  fetchAIEvaluationRuns,
  runOfflineResumeEvaluation,
  updateAIEvaluationErrorCase,
  type AiEvaluationDatasetRecord,
  type AiEvaluationErrorCaseRecord,
  type AiEvaluationErrorSeverity,
  type AiEvaluationErrorStatus,
  type AiEvaluationErrorType,
  type AiEvaluationResultRecord,
  type AiEvaluationRunRecord,
  type AiEvaluationRunStatus,
} from '../api/client'

const { Text, Title } = Typography

interface RunFormValues {
  modelName: string
  promptVersion: string
  forcedErrorCaseKeys?: string
}

const runStatusMeta: Record<AiEvaluationRunStatus, { label: string; color: string }> = {
  queued: { label: '排队中', color: 'default' },
  running: { label: '运行中', color: 'processing' },
  succeeded: { label: '通过', color: 'success' },
  failed: { label: '存在问题', color: 'error' },
  cancelled: { label: '已取消', color: 'default' },
}

const errorStatusMeta: Record<AiEvaluationErrorStatus, { label: string; color: string }> = {
  open: { label: '待处理', color: 'error' },
  resolved: { label: '已解决', color: 'success' },
  ignored: { label: '已忽略', color: 'default' },
}

const severityMeta: Record<AiEvaluationErrorSeverity, { label: string; color: string }> = {
  low: { label: '低', color: 'default' },
  medium: { label: '中', color: 'warning' },
  high: { label: '高', color: 'error' },
  critical: { label: '严重', color: 'red' },
}

const errorTypeLabels: Record<AiEvaluationErrorType, string> = {
  wrong_recommendation: '推荐结论错误',
  evidence_missing: '证据不足',
  hallucination: '幻觉',
  format_error: '格式错误',
  risk_omission: '风险遗漏',
  timeout: '超时',
  other: '其他错误',
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

function formatDuration(value: number | null) {
  if (value === null) return '—'
  if (value < 1000) return `${value}ms`
  return `${(value / 1000).toFixed(1)}s`
}

function scorePercent(value: number | null) {
  if (value === null) return '—'
  return `${Math.round(value * 100)}%`
}

function parseForcedKeys(value?: string) {
  return (value ?? '')
    .split(/[\s,，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export function AIEvaluationPage() {
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [runModalOpen, setRunModalOpen] = useState(false)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [runForm] = Form.useForm<RunFormValues>()

  const datasets = useQuery({
    queryKey: ['ai-evaluations', 'datasets'],
    queryFn: fetchAIEvaluationDatasets,
    staleTime: 15_000,
  })
  const runs = useQuery({
    queryKey: ['ai-evaluations', 'runs'],
    queryFn: () => fetchAIEvaluationRuns({ limit: 20, offset: 0 }),
    staleTime: 15_000,
  })
  const errorCases = useQuery({
    queryKey: ['ai-evaluations', 'error-cases'],
    queryFn: () => fetchAIEvaluationErrorCases({ limit: 50, offset: 0 }),
    staleTime: 15_000,
  })
  const selectedRun = useQuery({
    queryKey: ['ai-evaluations', 'runs', selectedRunId],
    queryFn: () => fetchAIEvaluationRun(selectedRunId!),
    enabled: Boolean(selectedRunId),
    staleTime: 15_000,
  })

  const latestRun = runs.data?.items[0]
  const openErrorCount = useMemo(
    () => (errorCases.data?.items ?? []).filter((item) => item.status === 'open').length,
    [errorCases.data?.items],
  )

  const initializeDataset = useMutation({
    mutationFn: createDefaultResumeEvaluationDataset,
    onSuccess: async () => {
      messageApi.success('默认评测集已就绪')
      await queryClient.invalidateQueries({ queryKey: ['ai-evaluations'] })
    },
    onError: (error) => messageApi.error(error.message),
  })

  const runEvaluation = useMutation({
    mutationFn: (values: RunFormValues) =>
      runOfflineResumeEvaluation({
        modelName: values.modelName,
        promptVersion: values.promptVersion,
        forcedErrorCaseKeys: parseForcedKeys(values.forcedErrorCaseKeys),
      }),
    onSuccess: async (run) => {
      messageApi.success('离线评测已完成')
      setRunModalOpen(false)
      setSelectedRunId(run.id)
      await queryClient.invalidateQueries({ queryKey: ['ai-evaluations'] })
    },
    onError: (error) => messageApi.error(error.message),
  })

  const updateErrorCase = useMutation({
    mutationFn: ({
      caseId,
      status,
      remediationNote,
    }: {
      caseId: string
      status: AiEvaluationErrorStatus
      remediationNote?: string
    }) => updateAIEvaluationErrorCase(caseId, status, remediationNote),
    onSuccess: async () => {
      messageApi.success('错误案例状态已更新')
      await queryClient.invalidateQueries({ queryKey: ['ai-evaluations', 'error-cases'] })
    },
    onError: (error) => messageApi.error(error.message),
  })

  function refreshAll() {
    void datasets.refetch()
    void runs.refetch()
    void errorCases.refetch()
    if (selectedRunId) void selectedRun.refetch()
  }

  function openRunModal() {
    runForm.setFieldsValue({
      modelName: 'deterministic-evaluator',
      promptVersion: 'synthetic-baseline-v1',
      forcedErrorCaseKeys: '',
    })
    setRunModalOpen(true)
  }

  const hasLoadError = datasets.isError || runs.isError || errorCases.isError

  return (
    <div className="ai-evaluation-page">
      {contextHolder}
      <section className="page-heading ai-evaluation-heading">
        <div>
          <Title level={2}>AI 评测与错误案例库</Title>
          <Text type="secondary">
            用固定合成样本验证模型和 Prompt 表现，沉淀证据不足、误判和幻觉等错误案例。
          </Text>
        </div>
        <Space wrap>
          <Button
            icon={<ReloadOutlined />}
            onClick={refreshAll}
            loading={datasets.isFetching || runs.isFetching || errorCases.isFetching}
          >
            刷新
          </Button>
          <Button
            icon={<ExperimentOutlined />}
            onClick={() => initializeDataset.mutate()}
            loading={initializeDataset.isPending}
          >
            初始化默认评测集
          </Button>
          <Button type="primary" icon={<PlayCircleOutlined />} onClick={openRunModal}>
            运行离线评测
          </Button>
        </Space>
      </section>

      {hasLoadError && (
        <Alert
          type="error"
          showIcon
          className="page-alert"
          message="无法读取 AI 评测数据"
          description="请确认当前账号具备管理员权限，且后端服务正常。"
        />
      )}

      <section className="ai-evaluation-metrics">
        <Card>
          <Statistic title="评测数据集" value={datasets.data?.items.length ?? 0} />
        </Card>
        <Card>
          <Statistic title="最近通过率" value={scorePercent(latestRun?.average_score ?? null)} />
        </Card>
        <Card>
          <Statistic title="最近失败样本" value={latestRun?.failed_samples ?? 0} />
        </Card>
        <Card>
          <Statistic title="待处理错误案例" value={openErrorCount} />
        </Card>
      </section>

      <Tabs
        className="ai-evaluation-tabs"
        items={[
          {
            key: 'runs',
            label: '评测运行',
            children: (
              <Space direction="vertical" size="large" className="ai-evaluation-stack">
                <Table<AiEvaluationRunRecord>
                  rowKey="id"
                  loading={runs.isPending}
                  dataSource={runs.data?.items ?? []}
                  pagination={false}
                  locale={{ emptyText: <Empty description="暂无评测运行" /> }}
                  onRow={(record) => ({
                    onClick: () => setSelectedRunId(record.id),
                  })}
                  columns={[
                    {
                      title: '运行名称',
                      key: 'name',
                      render: (_, record) => (
                        <Space direction="vertical" size={2}>
                          <Text strong>{record.name}</Text>
                          <Text type="secondary">{record.prompt_version ?? '未绑定 Prompt'}</Text>
                        </Space>
                      ),
                    },
                    {
                      title: '状态',
                      dataIndex: 'status',
                      width: 120,
                      render: (status: AiEvaluationRunStatus) => (
                        <Tag color={runStatusMeta[status].color}>
                          {runStatusMeta[status].label}
                        </Tag>
                      ),
                    },
                    { title: '模型', dataIndex: 'model_name', width: 180 },
                    {
                      title: '样本',
                      key: 'samples',
                      width: 140,
                      render: (_, record) => `${record.completed_samples}/${record.total_samples}`,
                    },
                    {
                      title: '平均分',
                      dataIndex: 'average_score',
                      width: 100,
                      render: scorePercent,
                    },
                    {
                      title: '耗时',
                      dataIndex: 'duration_ms',
                      width: 100,
                      render: formatDuration,
                    },
                    {
                      title: '完成时间',
                      dataIndex: 'completed_at',
                      width: 180,
                      render: formatDateTime,
                    },
                  ]}
                />

                <Card
                  title="运行详情"
                  className="ai-evaluation-detail-card"
                  extra={selectedRunId ? <Tag>{selectedRunId.slice(0, 8)}</Tag> : null}
                >
                  {!selectedRunId ? (
                    <Empty description="点击上方运行记录查看样本结果" />
                  ) : (
                    <Table<AiEvaluationResultRecord>
                      rowKey="id"
                      loading={selectedRun.isPending}
                      dataSource={selectedRun.data?.results ?? []}
                      pagination={{ pageSize: 8 }}
                      scroll={{ x: 960 }}
                      columns={[
                        {
                          title: '结果',
                          dataIndex: 'status',
                          width: 100,
                          render: (status: string) => (
                            <Tag color={status === 'passed' ? 'success' : 'error'}>{status}</Tag>
                          ),
                        },
                        {
                          title: '分数',
                          dataIndex: 'score',
                          width: 90,
                          render: scorePercent,
                        },
                        {
                          title: '推荐结论',
                          key: 'recommendation',
                          render: (_, record) =>
                            String(record.actual_output.recommendation ?? '未返回'),
                        },
                        {
                          title: '证据覆盖',
                          dataIndex: 'evidence_coverage_score',
                          width: 110,
                          render: scorePercent,
                        },
                        {
                          title: '错误类型',
                          dataIndex: 'error_types',
                          render: (types: AiEvaluationErrorType[]) =>
                            types.length ? (
                              <Space wrap>
                                {types.map((type) => (
                                  <Tag color="error" key={type}>
                                    {errorTypeLabels[type]}
                                  </Tag>
                                ))}
                              </Space>
                            ) : (
                              <Tag color="success">无</Tag>
                            ),
                        },
                        {
                          title: 'Token',
                          key: 'tokens',
                          width: 120,
                          render: (_, record) => record.total_tokens ?? '—',
                        },
                      ]}
                    />
                  )}
                </Card>
              </Space>
            ),
          },
          {
            key: 'errors',
            label: '错误案例库',
            children: (
              <Table<AiEvaluationErrorCaseRecord>
                rowKey="id"
                loading={errorCases.isPending}
                dataSource={errorCases.data?.items ?? []}
                pagination={{ pageSize: 10 }}
                locale={{ emptyText: <Empty description="暂无错误案例" /> }}
                scroll={{ x: 1100 }}
                columns={[
                  {
                    title: '案例',
                    key: 'title',
                    render: (_, record) => (
                      <Space direction="vertical" size={2}>
                        <Text strong>{record.title}</Text>
                        <Text type="secondary">{record.description ?? '无描述'}</Text>
                      </Space>
                    ),
                  },
                  {
                    title: '错误类型',
                    dataIndex: 'error_type',
                    width: 140,
                    render: (type: AiEvaluationErrorType) => errorTypeLabels[type],
                  },
                  {
                    title: '严重度',
                    dataIndex: 'severity',
                    width: 100,
                    render: (severity: AiEvaluationErrorSeverity) => (
                      <Tag color={severityMeta[severity].color}>{severityMeta[severity].label}</Tag>
                    ),
                  },
                  {
                    title: '状态',
                    dataIndex: 'status',
                    width: 110,
                    render: (status: AiEvaluationErrorStatus) => (
                      <Tag color={errorStatusMeta[status].color}>{errorStatusMeta[status].label}</Tag>
                    ),
                  },
                  {
                    title: '期望行为',
                    dataIndex: 'expected_behavior',
                    width: 260,
                    render: (value: string | null) => value ?? '—',
                  },
                  {
                    title: '处理',
                    key: 'actions',
                    width: 180,
                    fixed: 'right',
                    render: (_, record) =>
                      record.status === 'open' ? (
                        <Space>
                          <Button
                            size="small"
                            icon={<CheckCircleOutlined />}
                            loading={updateErrorCase.isPending}
                            onClick={() =>
                              updateErrorCase.mutate({
                                caseId: record.id,
                                status: 'resolved',
                                remediationNote: '已人工确认并纳入 Prompt/模型复盘',
                              })
                            }
                          >
                            标记解决
                          </Button>
                          <Button
                            size="small"
                            onClick={() =>
                              updateErrorCase.mutate({
                                caseId: record.id,
                                status: 'ignored',
                                remediationNote: '人工确认本案例暂不处理',
                              })
                            }
                          >
                            忽略
                          </Button>
                        </Space>
                      ) : (
                        <Text type="secondary">{record.remediation_note ?? '已处理'}</Text>
                      ),
                  },
                ]}
              />
            ),
          },
          {
            key: 'datasets',
            label: '评测数据集',
            children: (
              <Table<AiEvaluationDatasetRecord>
                rowKey="id"
                loading={datasets.isPending}
                dataSource={datasets.data?.items ?? []}
                pagination={false}
                locale={{ emptyText: <Empty description="暂无评测数据集" /> }}
                columns={[
                  { title: '名称', dataIndex: 'name' },
                  { title: '编码', dataIndex: 'code' },
                  { title: '场景', dataIndex: 'scenario' },
                  { title: '版本', dataIndex: 'version_number', width: 90 },
                  {
                    title: '状态',
                    dataIndex: 'status',
                    width: 100,
                    render: (status: string) => (
                      <Tag color={status === 'active' ? 'success' : 'default'}>{status}</Tag>
                    ),
                  },
                  {
                    title: '创建时间',
                    dataIndex: 'created_at',
                    width: 180,
                    render: formatDateTime,
                  },
                ]}
              />
            ),
          },
        ]}
      />

      <Modal
        title="运行离线评测"
        open={runModalOpen}
        onCancel={() => setRunModalOpen(false)}
        onOk={() => runForm.submit()}
        okText="开始评测"
        confirmLoading={runEvaluation.isPending}
      >
        <Form<RunFormValues>
          form={runForm}
          layout="vertical"
          onFinish={(values) => runEvaluation.mutate(values)}
        >
          <Form.Item name="modelName" label="模型名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="promptVersion" label="Prompt 版本" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="forcedErrorCaseKeys"
            label="模拟失败样本"
            extra="可选，用逗号或空格分隔，例如 BE-01 DA-01；留空则基线评测全部通过。"
          >
            <Input placeholder="BE-01, DA-01" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
