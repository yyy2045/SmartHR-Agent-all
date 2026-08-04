import {
  ApiOutlined,
  BranchesOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import { Button, Card, Space, Tag, Typography } from 'antd'
import type { ReactNode } from 'react'

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
  next: { label: '下一步开发', color: 'processing' },
  planned: { label: '计划中', color: 'default' },
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

export function AIConsolePage() {
  return (
    <div className="ai-console-page">
      <section className="page-heading ai-console-heading">
        <div>
          <Title level={2}>AI Agent 工程化专项</Title>
          <Text type="secondary">
            招聘闭环作为业务载体，重点展示 AI 可观测、PromptOps、RAG、Agent 和评测治理。
          </Text>
        </div>
        <Space size="small" wrap>
          <Tag color="blue">AI-00</Tag>
          <Tag color="success">导航骨架</Tag>
        </Space>
      </section>

      <section className="ai-console-overview" aria-label="AI 工程化概览">
        <div>
          <Text type="secondary">当前专项</Text>
          <strong>5</strong>
          <span>项核心 AI 工程能力</span>
        </div>
        <div>
          <Text type="secondary">当前阶段</Text>
          <strong>AI-00</strong>
          <span>入口与项目定位已建立</span>
        </div>
        <div>
          <Text type="secondary">下一小功能</Text>
          <strong>AI-01</strong>
          <span>调用日志与任务中心</span>
        </div>
      </section>

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
              <Button disabled block>
                待接入
              </Button>
            </Card>
          )
        })}
      </section>
    </div>
  )
}
