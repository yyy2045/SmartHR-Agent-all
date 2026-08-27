import {
  ArrowLeftOutlined,
  FileTextOutlined,
  MessageOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  SendOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Collapse,
  Empty,
  Input,
  List,
  Skeleton,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  ApiError,
  askCandidateAgent,
  createCandidateAgentSession,
  fetchCandidateAgentReport,
  fetchCandidateAgentSession,
  fetchCandidateAgentSessions,
  fetchJob,
  generateCandidateAgentReport,
  type CandidateAgentExchangeRecord,
  type CandidateAgentRecommendation,
} from '../api/client'

const { Title, Text, Paragraph } = Typography

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function fieldText(item: Record<string, unknown>, key: string) {
  const value = item[key]
  return typeof value === 'string' ? value : ''
}

function statusColor(status: CandidateAgentExchangeRecord['status']) {
  if (status === 'succeeded') return 'success'
  if (status === 'manual_fallback') return 'warning'
  if (status === 'failed') return 'error'
  return 'processing'
}

function recommendationLabel(value: CandidateAgentRecommendation) {
  const labels: Record<CandidateAgentRecommendation, string> = {
    hire: '建议录用',
    next_round: '建议进入下一轮',
    reserve: '进入人才库',
    reject: '不建议推进',
  }
  return labels[value]
}

function recommendationColor(value: CandidateAgentRecommendation) {
  if (value === 'hire') return 'success'
  if (value === 'next_round') return 'processing'
  if (value === 'reserve') return 'warning'
  return 'error'
}

function ReportListSection({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div className="candidate-agent-report-section">
      <Text strong>{title}</Text>
      <ul className="candidate-agent-report-list">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

export function CandidateAgentPage() {
  const { jobId, applicationId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [activeSessionId, setActiveSessionId] = useState<string>()
  const [question, setQuestion] = useState('')

  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
  })
  const sessions = useQuery({
    queryKey: ['candidate-agent-sessions', jobId, applicationId],
    queryFn: () => fetchCandidateAgentSessions(jobId!, applicationId!),
    enabled: Boolean(jobId && applicationId),
  })
  const activeSession = useQuery({
    queryKey: ['candidate-agent-session', jobId, applicationId, activeSessionId],
    queryFn: () => fetchCandidateAgentSession(jobId!, applicationId!, activeSessionId!),
    enabled: Boolean(jobId && applicationId && activeSessionId),
  })

  useEffect(() => {
    if (!activeSessionId && sessions.data?.length) {
      setActiveSessionId(sessions.data[0].id)
    }
  }, [activeSessionId, sessions.data])

  const createSession = useMutation({
    mutationFn: () =>
      createCandidateAgentSession(
        jobId!,
        applicationId!,
        `候选人问答 ${new Date().toLocaleDateString('zh-CN')}`,
      ),
    onSuccess: async (session) => {
      setActiveSessionId(session.id)
      await queryClient.invalidateQueries({
        queryKey: ['candidate-agent-sessions', jobId, applicationId],
      })
      messageApi.success('已创建候选人 AI 助手会话')
    },
  })
  const askMutation = useMutation({
    mutationFn: () =>
      askCandidateAgent(
        jobId!,
        applicationId!,
        activeSessionId!,
        question.trim(),
        crypto.randomUUID(),
      ),
    onSuccess: async (exchange) => {
      setQuestion('')
      if (exchange.status === 'manual_fallback') {
        messageApi.warning('AI 暂时不可用，已保存为人工降级记录')
      }
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['candidate-agent-session', jobId, applicationId, activeSessionId],
        }),
        queryClient.invalidateQueries({
          queryKey: ['candidate-agent-sessions', jobId, applicationId],
        }),
      ])
    },
  })

  const report = useQuery({
    queryKey: ['candidate-agent-report', jobId, applicationId],
    queryFn: () => fetchCandidateAgentReport(jobId!, applicationId!),
    enabled: Boolean(jobId && applicationId),
  })
  const generateReport = useMutation({
    mutationFn: () => generateCandidateAgentReport(jobId!, applicationId!, crypto.randomUUID()),
    onSuccess: async (record) => {
      if (record.status === 'manual_fallback') {
        messageApi.warning('AI 研判暂时不可用，已保存为人工降级记录')
      } else {
        messageApi.success('研判报告已生成')
      }
      await queryClient.invalidateQueries({
        queryKey: ['candidate-agent-report', jobId, applicationId],
      })
    },
  })

  const reportData = report.data

  const pageError = job.error ?? sessions.error ?? activeSession.error
  const exchanges = useMemo(
    () => activeSession.data?.exchanges ?? [],
    [activeSession.data?.exchanges],
  )

  return (
    <>
      {contextHolder}
      <div className="page-heading">
        <div>
          <Button
            type="link"
            icon={<ArrowLeftOutlined />}
            className="semantic-back-link"
            onClick={() => navigate(`/jobs/${jobId}/pipeline`)}
          >
            返回候选人流程
          </Button>
          <Title level={2}>候选人 AI 助手</Title>
          <Text type="secondary">
            围绕当前职位下的应聘记录提问，AI 只做证据分析，不自动做录用或淘汰决策。
          </Text>
        </div>
        <Space>
          <Button
            icon={<FileTextOutlined />}
            loading={generateReport.isPending}
            onClick={() => generateReport.mutate()}
          >
            生成研判报告
          </Button>
          <Button
            icon={<ReloadOutlined />}
            loading={sessions.isFetching || activeSession.isFetching}
            onClick={() => {
              void sessions.refetch()
              void activeSession.refetch()
            }}
          >
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            loading={createSession.isPending}
            onClick={() => createSession.mutate()}
          >
            新建会话
          </Button>
        </Space>
      </div>

      {(job.isError || sessions.isError || activeSession.isError) && (
        <Alert
          type="error"
          showIcon
          className="page-alert"
          message="无法读取候选人 AI 助手"
          description={
            pageError instanceof ApiError ? pageError.message : '请稍后重试'
          }
        />
      )}

      <div className="candidate-agent-layout">
        <Card
          title={job.data?.title ?? '当前职位'}
          className="candidate-agent-sessions"
          extra={<Tag color="blue">Agent</Tag>}
        >
          {sessions.isPending && <Skeleton active paragraph={{ rows: 5 }} />}
          {sessions.isSuccess && sessions.data.length === 0 && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="还没有问答会话"
            />
          )}
          {sessions.isSuccess && sessions.data.length > 0 && (
            <List
              dataSource={sessions.data}
              renderItem={(session) => (
                <List.Item
                  className={
                    session.id === activeSessionId
                      ? 'candidate-agent-session candidate-agent-session--active'
                      : 'candidate-agent-session'
                  }
                  onClick={() => setActiveSessionId(session.id)}
                >
                  <List.Item.Meta
                    avatar={<MessageOutlined />}
                    title={session.title || '未命名会话'}
                    description={formatDate(session.updated_at)}
                  />
                </List.Item>
              )}
            />
          )}
        </Card>

        <Card className="candidate-agent-chat" title="问答记录">
          {!activeSessionId && (
            <Empty description="请先新建或选择一个会话" />
          )}
          {activeSessionId && activeSession.isPending && (
            <Skeleton active paragraph={{ rows: 8 }} />
          )}
          {activeSessionId && activeSession.isSuccess && exchanges.length === 0 && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="可以开始询问候选人与当前职位的匹配、风险和下一步追问"
            />
          )}
          <Space direction="vertical" size="middle" className="candidate-agent-exchanges">
            {exchanges.map((exchange) => (
              <div className="candidate-agent-exchange" key={exchange.id}>
                <div className="candidate-agent-question">
                  <Text strong>你问：</Text>
                  <Paragraph>{exchange.question}</Paragraph>
                </div>
                <div className="candidate-agent-answer">
                  <Space size="small">
                    <RobotOutlined />
                    <Text strong>AI 回答</Text>
                    <Tag color={statusColor(exchange.status)}>{exchange.status}</Tag>
                    {exchange.model_name && <Tag>{exchange.model_name}</Tag>}
                    {exchange.prompt_version && <Tag>{exchange.prompt_version}</Tag>}
                  </Space>
                  <Paragraph>{exchange.answer || '正在生成或等待人工处理。'}</Paragraph>
                  {exchange.failure_message && (
                    <Alert
                      type="warning"
                      showIcon
                      message="本轮已降级"
                      description={exchange.failure_message}
                    />
                  )}
                  {exchange.evidence_references.length > 0 && (
                    <div className="candidate-agent-evidence">
                      <Text strong>证据引用</Text>
                      {exchange.evidence_references.map((item, index) => (
                        <blockquote key={`${exchange.id}-evidence-${index}`}>
                          <Text>{fieldText(item, 'source_label') || '业务证据'}</Text>
                          {fieldText(item, 'quote') && (
                            <Paragraph>{fieldText(item, 'quote')}</Paragraph>
                          )}
                        </blockquote>
                      ))}
                    </div>
                  )}
                  {exchange.knowledge_citations.length > 0 && (
                    <div className="candidate-agent-evidence">
                      <Text strong>知识库引用</Text>
                      {exchange.knowledge_citations.map((item, index) => (
                        <blockquote key={`${exchange.id}-knowledge-${index}`}>
                          <Text>{fieldText(item, 'document_title') || '知识文档'}</Text>
                          {fieldText(item, 'snippet') && (
                            <Paragraph>{fieldText(item, 'snippet')}</Paragraph>
                          )}
                        </blockquote>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </Space>
          <div className="candidate-agent-input">
            <Input.TextArea
              rows={4}
              maxLength={2000}
              showCount
              value={question}
              placeholder="例如：这个候选人最大的风险是什么？如果进入下一轮，应该重点追问什么？"
              onChange={(event) => setQuestion(event.target.value)}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={askMutation.isPending}
              disabled={!activeSessionId || !question.trim()}
              onClick={() => askMutation.mutate()}
            >
              发送给 AI
            </Button>
          </div>
        </Card>
      </div>

      {reportData && (
        <Card
          className="candidate-agent-report"
          title={
            <Space>
              <FileTextOutlined />
              <span>研判报告</span>
              <Tag color={reportData.status === 'succeeded' ? 'success' : 'warning'}>
                {reportData.status}
              </Tag>
              {reportData.model_name && <Tag>{reportData.model_name}</Tag>}
              {reportData.prompt_version && <Tag>{reportData.prompt_version}</Tag>}
            </Space>
          }
        >
          {reportData.status === 'manual_fallback' && (
            <Alert
              type="warning"
              showIcon
              className="page-alert"
              message="AI 研判已降级"
              description={reportData.failure_message}
            />
          )}
          {reportData.overall_recommendation && (
            <div className="candidate-agent-report-section">
              <Text strong>综合建议：</Text>
              <Tag color={recommendationColor(reportData.overall_recommendation)}>
                {recommendationLabel(reportData.overall_recommendation)}
              </Tag>
            </div>
          )}
          {reportData.match_assessment && (
            <div className="candidate-agent-report-section">
              <Text strong>匹配度研判</Text>
              <Paragraph>{reportData.match_assessment}</Paragraph>
            </div>
          )}
          <ReportListSection title="亮点" items={reportData.strengths} />
          <ReportListSection title="风险" items={reportData.risks} />
          <ReportListSection title="矛盾点" items={reportData.contradictions} />
          <ReportListSection title="证据缺口" items={reportData.evidence_gaps} />
          <ReportListSection title="下一步建议" items={reportData.next_step_suggestions} />
          <ReportListSection title="待核实问题" items={reportData.open_questions} />
          {reportData.evidence_references.length > 0 && (
            <div className="candidate-agent-report-section">
              <Text strong>证据引用</Text>
              {reportData.evidence_references.map((item, index) => (
                <blockquote key={`report-evidence-${index}`}>
                  <Text>{fieldText(item, 'source_label') || '业务证据'}</Text>
                  {fieldText(item, 'quote') && (
                    <Paragraph>{fieldText(item, 'quote')}</Paragraph>
                  )}
                </blockquote>
              ))}
            </div>
          )}
          {reportData.knowledge_citations.length > 0 && (
            <div className="candidate-agent-report-section">
              <Text strong>知识库引用</Text>
              {reportData.knowledge_citations.map((item, index) => (
                <blockquote key={`report-knowledge-${index}`}>
                  <Text>{fieldText(item, 'document_title') || '知识文档'}</Text>
                  {fieldText(item, 'snippet') && (
                    <Paragraph>{fieldText(item, 'snippet')}</Paragraph>
                  )}
                </blockquote>
              ))}
            </div>
          )}
          {reportData.tool_trajectory.length > 0 && (
            <Collapse
              ghost
              items={[
                {
                  key: 'trajectory',
                  label: `分析过程（${reportData.tool_trajectory.length} 步）`,
                  children: (
                    <List
                      size="small"
                      dataSource={reportData.tool_trajectory}
                      renderItem={(tool) => (
                        <List.Item>
                          <Space>
                            <Tag>第 {tool.step} 步</Tag>
                            <Text strong>{tool.name}</Text>
                            <Tag
                              color={tool.status === 'succeeded' ? 'success' : 'error'}
                            >
                              {tool.status}
                            </Tag>
                            {tool.error && <Text type="danger">{tool.error}</Text>}
                          </Space>
                        </List.Item>
                      )}
                    />
                  ),
                },
              ]}
            />
          )}
        </Card>
      )}
    </>
  )
}
