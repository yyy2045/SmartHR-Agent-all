import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  FileDoneOutlined,
  ReloadOutlined,
  SaveOutlined,
  SendOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Divider,
  Empty,
  Input,
  Modal,
  Radio,
  Skeleton,
  Space,
  Statistic,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  ApiError,
  fetchCandidateProcesses,
  fetchInterviewEvaluation,
  fetchJob,
  saveInterviewEvaluationDraft,
  submitInterviewEvaluation,
  type InterviewEvaluationContext,
  type InterviewEvaluationDraftInput,
  type OverallRecommendation,
} from '../api/client'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

interface QuestionDraft {
  answerSummary: string
  evidence: string
}

interface RatingDraft {
  score: number | null
  evidence: string
}

interface EvaluationDraft {
  overallRecommendation: OverallRecommendation | null
  overallComment: string
  questions: Record<string, QuestionDraft>
  ratings: Record<string, RatingDraft>
}

const recommendationMeta: Record<
  OverallRecommendation,
  { label: string; color: string }
> = {
  strongly_recommend: { label: '强烈推荐', color: 'green' },
  recommend: { label: '推荐', color: 'blue' },
  reserve: { label: '保留', color: 'orange' },
  not_recommend: { label: '不推荐', color: 'red' },
}

function emptyDraft(): EvaluationDraft {
  return {
    overallRecommendation: null,
    overallComment: '',
    questions: {},
    ratings: {},
  }
}

function draftFromContext(context: InterviewEvaluationContext): EvaluationDraft {
  const responseByQuestion = new Map(
    context.evaluation?.question_responses.map((item) => [item.question_id, item]),
  )
  const ratingByDimension = new Map(
    context.evaluation?.dimension_ratings.map((item) => [item.dimension_id, item]),
  )
  return {
    overallRecommendation: context.evaluation?.overall_recommendation ?? null,
    overallComment: context.evaluation?.overall_comment ?? '',
    questions: Object.fromEntries(
      context.questions.map((question) => {
        const response = responseByQuestion.get(question.id)
        return [
          question.id,
          {
            answerSummary: response?.answer_summary ?? '',
            evidence: response?.evidence ?? '',
          },
        ]
      }),
    ),
    ratings: Object.fromEntries(
      context.dimensions.map((dimension) => {
        const rating = ratingByDimension.get(dimension.id)
        return [
          dimension.id,
          { score: rating?.score ?? null, evidence: rating?.evidence ?? '' },
        ]
      }),
    ),
  }
}

function payloadFromDraft(
  context: InterviewEvaluationContext,
  draft: EvaluationDraft,
): InterviewEvaluationDraftInput {
  return {
    overall_recommendation: draft.overallRecommendation,
    overall_comment: draft.overallComment.trim(),
    question_responses: context.questions.map((question) => ({
      question_id: question.id,
      answer_summary: draft.questions[question.id]?.answerSummary.trim() ?? '',
      evidence: draft.questions[question.id]?.evidence.trim() ?? '',
    })),
    dimension_ratings: context.dimensions.map((dimension) => ({
      dimension_id: dimension.id,
      score: draft.ratings[dimension.id]?.score ?? null,
      evidence: draft.ratings[dimension.id]?.evidence.trim() ?? '',
    })),
  }
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function validateForSubmit(
  context: InterviewEvaluationContext,
  draft: EvaluationDraft,
): string | undefined {
  if (!draft.overallRecommendation) return '请选择总体建议'
  for (const question of context.questions) {
    const response = draft.questions[question.id]
    if (!response?.answerSummary.trim() || !response.evidence.trim()) {
      return `请完整填写问题“${question.question_text}”的回答摘要和事实证据`
    }
  }
  for (const dimension of context.dimensions) {
    const rating = draft.ratings[dimension.id]
    if (!rating?.score || !rating.evidence.trim()) {
      return `请完整填写评分维度“${dimension.name}”的分数和评分依据`
    }
  }
  return undefined
}

export function InterviewEvaluationPage() {
  const { jobId, documentId, roundId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [draft, setDraft] = useState<EvaluationDraft>(emptyDraft)
  const [submitConfirmOpen, setSubmitConfirmOpen] = useState(false)

  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
  })
  const candidates = useQuery({
    queryKey: ['candidate-processes', jobId],
    queryFn: () => fetchCandidateProcesses(jobId!),
    enabled: Boolean(jobId),
  })
  const evaluation = useQuery({
    queryKey: ['interview-evaluation', jobId, documentId, roundId],
    queryFn: () => fetchInterviewEvaluation(jobId!, documentId!, roundId!),
    enabled: Boolean(jobId && documentId && roundId),
  })

  useEffect(() => {
    if (evaluation.data) setDraft(draftFromContext(evaluation.data))
  }, [evaluation.data])

  const candidate = candidates.data?.find((item) => item.document_id === documentId)
  const archived = job.data?.status === 'archived'
  const submitted = evaluation.data?.evaluation?.status === 'submitted'
  const cancelled = evaluation.data?.round_status === 'cancelled'
  const readOnly = Boolean(archived || submitted || cancelled)
  const pageError = job.error ?? candidates.error ?? evaluation.error
  const loading = job.isPending || candidates.isPending || evaluation.isPending

  const completion = useMemo(() => {
    if (!evaluation.data) return { answered: 0, rated: 0, score: 0 }
    const answered = evaluation.data.questions.filter((question) => {
      const response = draft.questions[question.id]
      return response?.answerSummary.trim() && response.evidence.trim()
    }).length
    const rated = evaluation.data.dimensions.filter((dimension) => {
      const rating = draft.ratings[dimension.id]
      return rating?.score && rating.evidence.trim()
    }).length
    const score = evaluation.data.dimensions.reduce((total, dimension) => {
      const rating = draft.ratings[dimension.id]
      return total + ((rating?.score ?? 0) / 5) * dimension.weight_percent
    }, 0)
    return { answered, rated, score }
  }, [draft, evaluation.data])

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!jobId || !documentId || !roundId || !evaluation.data) {
        throw new Error('缺少面试评价上下文')
      }
      return saveInterviewEvaluationDraft(
        jobId,
        documentId,
        roundId,
        payloadFromDraft(evaluation.data, draft),
      )
    },
    onSuccess: (result) => {
      queryClient.setQueryData(
        ['interview-evaluation', jobId, documentId, roundId],
        result,
      )
      void messageApi.success('面试评价草稿已保存')
    },
    onError: (error) => {
      void messageApi.error(error instanceof Error ? error.message : '保存评价草稿失败')
    },
  })

  const submitMutation = useMutation({
    mutationFn: async () => {
      if (!jobId || !documentId || !roundId || !evaluation.data) {
        throw new Error('缺少面试评价上下文')
      }
      const validationError = validateForSubmit(evaluation.data, draft)
      if (validationError) throw new Error(validationError)
      await saveInterviewEvaluationDraft(
        jobId,
        documentId,
        roundId,
        payloadFromDraft(evaluation.data, draft),
      )
      return submitInterviewEvaluation(jobId, documentId, roundId)
    },
    onSuccess: (result) => {
      queryClient.setQueryData(
        ['interview-evaluation', jobId, documentId, roundId],
        result,
      )
      setSubmitConfirmOpen(false)
      void messageApi.success('面试评价已提交并锁定')
    },
    onError: (error) => {
      void messageApi.error(error instanceof Error ? error.message : '提交面试评价失败')
    },
  })

  function confirmSubmit() {
    if (!evaluation.data) return
    const validationError = validateForSubmit(evaluation.data, draft)
    if (validationError) {
      void messageApi.error(validationError)
      return
    }
    setSubmitConfirmOpen(true)
  }

  return (
    <>
      {contextHolder}
      <div className="page-heading">
        <div>
          <Space size="small" wrap>
            <Title level={2}>{candidate?.candidate_code ?? '候选人面试评价'}</Title>
            {evaluation.data?.evaluation?.status === 'draft' && <Tag color="processing">草稿</Tag>}
            {submitted && <Tag color="success">已提交</Tag>}
          </Space>
          <Text type="secondary">
            {job.data?.title ? `${job.data.title} · ` : ''}
            {evaluation.data?.round_name ?? '读取面试轮次中'}
          </Text>
        </div>
        <Space wrap>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() =>
              navigate(`/jobs/${jobId}/candidates/${documentId}/interview-schedule`)
            }
          >
            返回面试安排
          </Button>
          <Button
            icon={<ReloadOutlined />}
            loading={evaluation.isFetching}
            onClick={() => void evaluation.refetch()}
          >
            刷新
          </Button>
        </Space>
      </div>

      {archived && (
        <Alert
          className="page-alert"
          type="warning"
          showIcon
          message="该职位已归档，面试评价仅供查看"
        />
      )}
      {cancelled && (
        <Alert
          className="page-alert"
          type="warning"
          showIcon
          message="该面试轮次已取消，不能填写或提交评价"
        />
      )}
      {submitted && (
        <Alert
          className="page-alert"
          type="success"
          showIcon
          message="评价已正式提交并锁定"
          description="以下内容为最终评价记录，不能继续修改。"
        />
      )}
      {pageError && (
        <Alert
          className="page-alert"
          type="error"
          showIcon
          message="无法读取面试评价"
          description={pageError instanceof ApiError ? pageError.message : '请稍后重试'}
          action={<Button onClick={() => void evaluation.refetch()}>重试</Button>}
        />
      )}
      {loading && <Skeleton active paragraph={{ rows: 12 }} />}

      {!loading && !pageError && evaluation.data && (
        <>
          <Card className="evaluation-overview-card">
            <div className="evaluation-overview-grid">
              <Statistic title="面试轮次" value={evaluation.data.round_name} />
              <Statistic
                title="计划时间"
                value={formatDateTime(evaluation.data.scheduled_start_at)}
              />
              <Statistic title="通过阈值" value={evaluation.data.pass_threshold} suffix="分" />
              <Statistic
                title={submitted ? '最终得分' : '当前预估得分'}
                value={
                  evaluation.data.evaluation?.total_score ?? Number(completion.score.toFixed(2))
                }
                suffix="分"
                valueStyle={
                  submitted
                    ? { color: evaluation.data.evaluation?.passed ? '#168a53' : '#cf3f3f' }
                    : undefined
                }
              />
            </div>
          </Card>

          <div className="evaluation-workbench">
            <main className="evaluation-main">
              <Card
                className="evaluation-section"
                title="面试问题记录"
                extra={
                  <Text type="secondary">
                    已完成 {completion.answered}/{evaluation.data.questions.length}
                  </Text>
                }
              >
                {evaluation.data.questions.length ? (
                  <Space direction="vertical" size="large" className="evaluation-item-list">
                    {evaluation.data.questions.map((question, index) => (
                      <section key={question.id} className="evaluation-question-item">
                        <div className="evaluation-item-heading">
                          <span className="evaluation-index">{index + 1}</span>
                          <div>
                            <Title level={4}>{question.question_text}</Title>
                            <Text type="secondary">
                              {question.evaluation_guide || '该问题暂未配置评价指引'}
                            </Text>
                          </div>
                        </div>
                        <div className="evaluation-field-grid">
                          <label>
                            <Text strong>回答摘要</Text>
                            <TextArea
                              aria-label={`回答摘要：${question.question_text}`}
                              rows={4}
                              value={draft.questions[question.id]?.answerSummary ?? ''}
                              disabled={readOnly}
                              placeholder="记录候选人的核心回答、思路和关键结论"
                              onChange={(event) =>
                                setDraft((current) => ({
                                  ...current,
                                  questions: {
                                    ...current.questions,
                                    [question.id]: {
                                      ...(current.questions[question.id] ?? {
                                        answerSummary: '',
                                        evidence: '',
                                      }),
                                      answerSummary: event.target.value,
                                    },
                                  },
                                }))
                              }
                            />
                          </label>
                          <label>
                            <Text strong>事实证据</Text>
                            <TextArea
                              aria-label={`事实证据：${question.question_text}`}
                              rows={4}
                              value={draft.questions[question.id]?.evidence ?? ''}
                              disabled={readOnly}
                              placeholder="记录候选人给出的数字、案例、职责边界或可验证事实"
                              onChange={(event) =>
                                setDraft((current) => ({
                                  ...current,
                                  questions: {
                                    ...current.questions,
                                    [question.id]: {
                                      ...(current.questions[question.id] ?? {
                                        answerSummary: '',
                                        evidence: '',
                                      }),
                                      evidence: event.target.value,
                                    },
                                  },
                                }))
                              }
                            />
                          </label>
                        </div>
                      </section>
                    ))}
                  </Space>
                ) : (
                  <Empty description="本轮没有配置面试问题" />
                )}
              </Card>

              <Card
                className="evaluation-section"
                title="结构化评分"
                extra={
                  <Text type="secondary">
                    已完成 {completion.rated}/{evaluation.data.dimensions.length}
                  </Text>
                }
              >
                <Space direction="vertical" size="large" className="evaluation-item-list">
                  {evaluation.data.dimensions.map((dimension) => {
                    const currentRating = draft.ratings[dimension.id]
                    const currentAnchor = dimension.anchors.find(
                      (anchor) => anchor.score_value === currentRating?.score,
                    )
                    return (
                      <section key={dimension.id} className="evaluation-rating-item">
                        <div className="evaluation-rating-heading">
                          <div>
                            <Title level={4}>{dimension.name}</Title>
                            <Text type="secondary">
                              {dimension.description || '暂无维度说明'}
                            </Text>
                          </div>
                          <Tag color="blue">权重 {dimension.weight_percent}%</Tag>
                        </div>
                        <Radio.Group
                          className="evaluation-score-group"
                          value={currentRating?.score}
                          disabled={readOnly}
                          onChange={(event) =>
                            setDraft((current) => ({
                              ...current,
                              ratings: {
                                ...current.ratings,
                                [dimension.id]: {
                                  ...(current.ratings[dimension.id] ?? {
                                    score: null,
                                    evidence: '',
                                  }),
                                  score: event.target.value as number,
                                },
                              },
                            }))
                          }
                        >
                          {[1, 2, 3, 4, 5].map((score) => (
                            <Radio.Button
                              key={score}
                              value={score}
                              aria-label={`${dimension.name} ${score} 分`}
                            >
                              {score} 分
                            </Radio.Button>
                          ))}
                        </Radio.Group>
                        <Alert
                          className="evaluation-anchor"
                          type={currentAnchor ? 'info' : 'warning'}
                          showIcon
                          message={
                            currentAnchor
                              ? `${currentAnchor.score_value} 分锚点：${currentAnchor.description}`
                              : '请选择分数以查看对应评分锚点'
                          }
                        />
                        <label>
                          <Text strong>评分依据</Text>
                          <TextArea
                            aria-label={`评分依据：${dimension.name}`}
                            rows={3}
                            value={currentRating?.evidence ?? ''}
                            disabled={readOnly}
                            placeholder="说明该分数对应的面试事实，避免只写主观结论"
                            onChange={(event) =>
                              setDraft((current) => ({
                                ...current,
                                ratings: {
                                  ...current.ratings,
                                  [dimension.id]: {
                                    ...(current.ratings[dimension.id] ?? {
                                      score: null,
                                      evidence: '',
                                    }),
                                    evidence: event.target.value,
                                  },
                                },
                              }))
                            }
                          />
                        </label>
                      </section>
                    )
                  })}
                </Space>
              </Card>
            </main>

            <aside className="evaluation-summary">
              <Card title="评价结论" className="evaluation-summary-card">
                {submitted && evaluation.data.evaluation ? (
                  <div className="evaluation-final-result">
                    <CheckCircleOutlined />
                    <Title level={3}>
                      {evaluation.data.evaluation.passed ? '通过' : '未通过'}
                    </Title>
                    <Text type="secondary">
                      得分 {evaluation.data.evaluation.total_score?.toFixed(2)} / 阈值{' '}
                      {evaluation.data.pass_threshold}
                    </Text>
                  </div>
                ) : (
                  <Alert
                    type="info"
                    showIcon
                    message="草稿可随时保存"
                    description="正式提交后服务端计算加权总分并永久锁定。"
                  />
                )}

                <Divider />
                <label className="evaluation-summary-field">
                  <Text strong>总体建议</Text>
                  <Radio.Group
                    className="evaluation-recommendation-group"
                    value={draft.overallRecommendation}
                    disabled={readOnly}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        overallRecommendation: event.target.value as OverallRecommendation,
                      }))
                    }
                  >
                    {(Object.entries(recommendationMeta) as Array<
                      [OverallRecommendation, { label: string; color: string }]
                    >).map(([value, meta]) => (
                      <Radio.Button key={value} value={value}>
                        {meta.label}
                      </Radio.Button>
                    ))}
                  </Radio.Group>
                </label>

                <label className="evaluation-summary-field">
                  <Text strong>总体评语</Text>
                  <TextArea
                    aria-label="总体评语"
                    rows={6}
                    value={draft.overallComment}
                    disabled={readOnly}
                    placeholder="总结候选人的优势、风险和后续建议"
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        overallComment: event.target.value,
                      }))
                    }
                  />
                </label>

                {draft.overallRecommendation && (
                  <Tag color={recommendationMeta[draft.overallRecommendation].color}>
                    当前建议：{recommendationMeta[draft.overallRecommendation].label}
                  </Tag>
                )}

                {!readOnly && (
                  <Space direction="vertical" className="evaluation-actions">
                    <Button
                      block
                      icon={<SaveOutlined />}
                      loading={saveMutation.isPending}
                      disabled={submitMutation.isPending}
                      onClick={() => saveMutation.mutate()}
                    >
                      保存草稿
                    </Button>
                    <Button
                      block
                      type="primary"
                      icon={<SendOutlined />}
                      loading={submitMutation.isPending}
                      disabled={saveMutation.isPending}
                      onClick={confirmSubmit}
                    >
                      正式提交并锁定
                    </Button>
                  </Space>
                )}
              </Card>

              <Card className="evaluation-summary-card" title="完成情况">
                <Space direction="vertical" className="evaluation-completion-list">
                  <Text>
                    问题记录：{completion.answered}/{evaluation.data.questions.length}
                  </Text>
                  <Text>
                    评分维度：{completion.rated}/{evaluation.data.dimensions.length}
                  </Text>
                  <Text>
                    总体建议：{draft.overallRecommendation ? '已选择' : '未选择'}
                  </Text>
                  <Text type="secondary">
                    当前预估加权分：{completion.score.toFixed(2)} 分
                  </Text>
                </Space>
              </Card>
            </aside>
          </div>
        </>
      )}

      {!loading && !pageError && !evaluation.data && (
        <Empty image={<FileDoneOutlined />} description="没有可用的面试评价上下文" />
      )}

      <Modal
        title="确认提交面试评价？"
        open={submitConfirmOpen}
        okText="确认提交"
        cancelText="继续检查"
        confirmLoading={submitMutation.isPending}
        onOk={() => submitMutation.mutate()}
        onCancel={() => setSubmitConfirmOpen(false)}
      >
        <Paragraph>提交后评价将永久锁定，不能继续修改。</Paragraph>
      </Modal>
    </>
  )
}
