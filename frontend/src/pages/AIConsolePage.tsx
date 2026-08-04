import {
  ApiOutlined,
  BranchesOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  ReloadOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Empty, Space, Table, Tabs, Tag, Typography } from 'antd'
import type { ReactNode } from 'react'

import {
  fetchAIObservabilityCalls,
  fetchAIObservabilitySummary,
  fetchAIObservabilityTasks,
  type AiCallLogRecord,
  type AiCallStatus,
  type AiTaskRecord,
  type AiTaskStatus,
} from '../api/client'

const { Text, Title } = Typography

type AiCapabilityStatus = 'ready' | 'next' | 'planned'

interface AiCapability {
  key: string
  title: string
  status: AiCapabilityStatus
  icon: ReactNode
  description: string
  checkpoints: string[]
}

const statusMeta: Record<AiCapabilityStatus, { label: string; color: string }> = {
  ready: { label: '入口已就绪', color: 'success' },
  next: { label: '当前开发', color: 'processing' },
  planned: { label: '计划中', color: 'default' },
}

const taskStatusMeta: Record<AiTaskStatus, { label: string; color: string }> = {
  queued: { label: '排队中', color: 'default' },
  running: { label: '处理中', color: 'processing' },
  succeeded: { label: '成功', color: 'success' },
  failed: { label: '失败', color: 'error' },
  retrying: { label: '重试中', color: 'warning' },
  cancelled: { label: '已取消', color: 'default' },
}

const callStatusMeta: Record<AiCallStatus, { label: string; color: string }> = {
  succeeded: { label: '成功', color: 'success' },
  failed: { label: '失败', color: 'error' },
}

const scenarioLabels: Record<string, string> = {
  jd_generation: 'JD 结构化',
  resume_parse: '简历解析',
  resume_analysis: '简历评分',
  resume_analysis_repair: '简历评分修复',
  interview_report: '面试报告',
  knowledge_indexing: '知识入库',
  talent_recommendation: '人才推荐',
  talent_recommendation_rescoring: '推荐重评',
  talent_recommendation_repair: '推荐修复',
}

const capabilities: AiCapability[] = [
  {
    key: 'ai-observability',
    title: 'AI 调用日志与任务中心',
    status: 'next',
    icon: <ApiOutlined />,
    description: '统一记录 AI 与异步任务的运行状态、耗时、Token、失败原因和重试轨迹。',
    checkpoints: ['OCR、解析、Embedding 与 AI 调用纳入同一任务视图', '失败可追踪，可人工降级'],
  },
  {
    key: 'promptops',
    title: 'Prompt 模板管理与版本化',
    status: 'planned',
    icon: <BranchesOutlined />,
    description: '把硬编码 Prompt 迁移为可发布、可回滚、可审计的业务模板。',
    checkpoints: ['场景化模板', '不可变版本', 'JSON Schema 输出约束'],
  },
  {
    key: 'enterprise-rag',
    title: '企业招聘知识库 RAG',
    status: 'planned',
    icon: <DatabaseOutlined />,
    description: '上传企业招聘制度、岗位标准和沟通话术，供 Agent 检索并引用来源。',
    checkpoints: ['文档分块与 Embedding', '标签分类', '权限过滤与引用快照'],
  },
  {
    key: 'candidate-agent',
    title: '候选人问答 Agent',
    status: 'planned',
    icon: <RobotOutlined />,
    description: '在候选人详情中提问，由 Agent 汇总简历、筛选、面试、Offer 和知识库证据。',
    checkpoints: ['异步会话', '证据化回答', '不自动推进招聘决策'],
  },
  {
    key: 'ai-evaluation',
    title: 'AI 评测与错误案例库',
    status: 'planned',
    icon: <ExperimentOutlined />,
    description: '用固定合成样本比较模型和 Prompt 版本，沉淀误判、幻觉和证据不足案例。',
    checkpoints: ['离线批量评测', '错误类型标记', '质量、Token 和耗时看板'],
  },
]

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

function scenarioLabel(value: string) {
  return scenarioLabels[value] ?? value
}

function resourceLabel(record: Pick<AiTaskRecord | AiCallLogRecord, 'resource_type' | 'resource_id'>) {
  if (!record.resource_type || !record.resource_id) return '—'
  return `${record.resource_type} / ${record.resource_id.slice(0, 8)}`
}

export function AIConsolePage() {
  const summary = useQuery({
    queryKey: ['ai-observability', 'summary'],
    queryFn: fetchAIObservabilitySummary,
    staleTime: 15_000,
  })
  const tasks = useQuery({
    queryKey: ['ai-observability', 'tasks'],
    queryFn: () => fetchAIObservabilityTasks({ limit: 20, offset: 0 }),
    staleTime: 15_000,
  })
  const calls = useQuery({
    queryKey: ['ai-observability', 'calls'],
    queryFn: () => fetchAIObservabilityCalls({ limit: 20, offset: 0 }),
    staleTime: 15_000,
  })

  function refreshAll() {
    void summary.refetch()
    void tasks.refetch()
    void calls.refetch()
  }

  const overview = summary.data

  return (
    <div className="ai-console-page">
      <section className="page-heading ai-console-heading">
        <div>
          <Title level={2}>AI Agent 工程化专项</Title>
          <Text type="secondary">
            招聘闭环是业务载体，重点展示 AI 可观测、PromptOps、RAG、Agent 和评测治理。
          </Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={refreshAll} loading={summary.isFetching}>
          刷新
        </Button>
      </section>

      {summary.isError && (
        <Alert
          type="error"
          showIcon
          className="page-alert"
          message="无法读取 AI 控制台数据"
          description={summary.error.message}
          action={<Button onClick={() => void summary.refetch()}>重试</Button>}
        />
      )}

      <section className="ai-console-overview" aria-label="AI 工程化概览">
        <div>
          <Text type="secondary">AI 任务</Text>
          <strong>{overview?.task_total ?? 0}</strong>
          <span>失败 {overview?.failed_task_count ?? 0} 个</span>
        </div>
        <div>
          <Text type="secondary">模型调用</Text>
          <strong>{overview?.call_total ?? 0}</strong>
          <span>失败 {overview?.failed_call_count ?? 0} 次</span>
        </div>
        <div>
          <Text type="secondary">Token 消耗</Text>
          <strong>{overview?.total_tokens ?? 0}</strong>
          <span>
            输入 {overview?.total_input_tokens ?? 0} / 输出 {overview?.total_output_tokens ?? 0}
          </span>
        </div>
        <div>
          <Text type="secondary">平均耗时</Text>
          <strong>{formatDuration(overview?.avg_call_duration_ms ?? null)}</strong>
          <span>任务 {formatDuration(overview?.avg_task_duration_ms ?? null)}</span>
        </div>
      </section>

      <Tabs
        className="ai-console-tabs"
        items={[
          {
            key: 'tasks',
            label: '任务中心',
            children: (
              <section className="panel-card ai-console-table-panel">
                <Table<AiTaskRecord>
                  rowKey="id"
                  loading={tasks.isPending}
                  dataSource={tasks.data?.items ?? []}
                  pagination={false}
                  locale={{ emptyText: <Empty description="暂无 AI 异步任务" /> }}
                  scroll={{ x: 1100 }}
                  columns={[
                    {
                      title: '任务',
                      key: 'task',
                      render: (_, record) => (
                        <Space direction="vertical" size={2}>
                          <Text strong>{record.task_name}</Text>
                          <Text type="secondary">{scenarioLabel(record.scenario)}</Text>
                        </Space>
                      ),
                    },
                    {
                      title: '状态',
                      dataIndex: 'status',
                      width: 110,
                      render: (status: AiTaskStatus) => (
                        <Tag color={taskStatusMeta[status].color}>
                          {taskStatusMeta[status].label}
                        </Tag>
                      ),
                    },
                    {
                      title: '资源',
                      key: 'resource',
                      width: 220,
                      render: (_, record) => resourceLabel(record),
                    },
                    {
                      title: '重试',
                      key: 'retry',
                      width: 100,
                      render: (_, record) => `${record.attempt_count}/${record.max_retries}`,
                    },
                    {
                      title: '耗时',
                      dataIndex: 'duration_ms',
                      width: 100,
                      render: formatDuration,
                    },
                    {
                      title: '开始/完成',
                      key: 'time',
                      width: 220,
                      render: (_, record) => (
                        <Space direction="vertical" size={2}>
                          <span>{formatDateTime(record.started_at)}</span>
                          <Text type="secondary">{formatDateTime(record.completed_at)}</Text>
                        </Space>
                      ),
                    },
                    {
                      title: '失败原因',
                      key: 'failure',
                      width: 260,
                      render: (_, record) =>
                        record.failure_code ? (
                          <Space direction="vertical" size={2}>
                            <Tag color="error">{record.failure_code}</Tag>
                            <Text type="secondary">{record.failure_message}</Text>
                          </Space>
                        ) : (
                          '—'
                        ),
                    },
                  ]}
                />
              </section>
            ),
          },
          {
            key: 'calls',
            label: '调用日志',
            children: (
              <section className="panel-card ai-console-table-panel">
                <Table<AiCallLogRecord>
                  rowKey="id"
                  loading={calls.isPending}
                  dataSource={calls.data?.items ?? []}
                  pagination={false}
                  locale={{ emptyText: <Empty description="暂无 AI 调用日志" /> }}
                  scroll={{ x: 1120 }}
                  columns={[
                    {
                      title: '场景',
                      dataIndex: 'scenario',
                      render: scenarioLabel,
                    },
                    {
                      title: '模型 / Prompt',
                      key: 'model',
                      width: 220,
                      render: (_, record) => (
                        <Space direction="vertical" size={2}>
                          <Text>{record.model_name ?? '未记录模型'}</Text>
                          <Text type="secondary">{record.prompt_version ?? '未绑定版本'}</Text>
                        </Space>
                      ),
                    },
                    {
                      title: '状态',
                      dataIndex: 'status',
                      width: 100,
                      render: (status: AiCallStatus) => (
                        <Tag color={callStatusMeta[status].color}>
                          {callStatusMeta[status].label}
                        </Tag>
                      ),
                    },
                    {
                      title: 'Token',
                      key: 'tokens',
                      width: 160,
                      render: (_, record) =>
                        `${record.total_tokens ?? 0}（${record.input_tokens ?? 0}/${record.output_tokens ?? 0}）`,
                    },
                    {
                      title: '耗时',
                      dataIndex: 'duration_ms',
                      width: 100,
                      render: formatDuration,
                    },
                    {
                      title: '资源',
                      key: 'resource',
                      width: 220,
                      render: (_, record) => resourceLabel(record),
                    },
                    {
                      title: '时间',
                      dataIndex: 'created_at',
                      width: 180,
                      render: formatDateTime,
                    },
                    {
                      title: '失败原因',
                      key: 'failure',
                      width: 240,
                      render: (_, record) =>
                        record.failure_code ? (
                          <Space direction="vertical" size={2}>
                            <Tag color="error">{record.failure_code}</Tag>
                            <Text type="secondary">{record.failure_message}</Text>
                          </Space>
                        ) : (
                          '—'
                        ),
                    },
                  ]}
                />
              </section>
            ),
          },
          {
            key: 'roadmap',
            label: '专项路线',
            children: (
              <section className="ai-capability-grid" aria-label="AI 专项能力">
                {capabilities.map((item) => {
                  const status = statusMeta[item.status]
                  return (
                    <Card
                      key={item.key}
                      className={`ai-capability-card ai-capability-card--${item.status}`}
                      title={
                        <Space size="small">
                          <span className="ai-capability-icon" aria-hidden="true">
                            {item.icon}
                          </span>
                          <span>{item.title}</span>
                        </Space>
                      }
                      extra={<Tag color={status.color}>{status.label}</Tag>}
                    >
                      <Text type="secondary">{item.description}</Text>
                      <ul>
                        {item.checkpoints.map((checkpoint) => (
                          <li key={checkpoint}>
                            <FileSearchOutlined />
                            <span>{checkpoint}</span>
                          </li>
                        ))}
                      </ul>
                      <Tag icon={<ClockCircleOutlined />}>按专项计划推进</Tag>
                    </Card>
                  )
                })}
              </section>
            ),
          },
        ]}
      />
    </div>
  )
}
