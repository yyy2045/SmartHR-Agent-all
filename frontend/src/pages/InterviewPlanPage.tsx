import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CheckOutlined,
  CopyOutlined,
  DeleteOutlined,
  PlusOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Popconfirm,
  Progress,
  Select,
  Skeleton,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'

import {
  ApiError,
  confirmInterviewPlanVersion,
  createInterviewPlanVersion,
  fetchInterviewPlanVersions,
  fetchJob,
  updateInterviewPlanDraft,
  type InterviewPlanDraftInput,
  type InterviewPlanVersion,
  type InterviewRoundType,
} from '../api/client'
import { useAuth } from '../auth/context'
import { canManageRecruitment } from '../auth/permissions'

const { Title, Text, Paragraph } = Typography
const anchorScores = [1, 2, 3, 4, 5]

const roundTypeOptions: Array<{ label: string; value: InterviewRoundType }> = [
  { label: '电话或视频初访', value: 'phone' },
  { label: '技术面试', value: 'technical' },
  { label: '业务面试', value: 'business' },
  { label: 'HR 面试', value: 'hr' },
  { label: '终面', value: 'final' },
  { label: '其他', value: 'other' },
]

const roundTypeLabels = Object.fromEntries(
  roundTypeOptions.map((item) => [item.value, item.label]),
) as Record<InterviewRoundType, string>

interface AnchorFormValue {
  score_value: number
  description: string
}

interface DimensionFormValue {
  name: string
  description: string
  weight_percent: number
  anchors: AnchorFormValue[]
}

interface QuestionFormValue {
  question_text: string
  evaluation_guide: string
}

interface RoundFormValue {
  name: string
  round_type: InterviewRoundType
  duration_minutes: number
  pass_threshold: number
  focus: string
  questions: QuestionFormValue[]
  scoring_dimensions: DimensionFormValue[]
}

interface InterviewPlanFormValues {
  rounds: RoundFormValue[]
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback
}

function emptyAnchors(): AnchorFormValue[] {
  return anchorScores.map((score) => ({ score_value: score, description: '' }))
}

function versionToForm(version: InterviewPlanVersion): InterviewPlanFormValues {
  return {
    rounds: version.rounds.map((round) => ({
      name: round.name,
      round_type: round.round_type,
      duration_minutes: round.duration_minutes,
      pass_threshold: round.pass_threshold,
      focus: round.focus,
      questions: round.questions.map((question) => ({
        question_text: question.question_text,
        evaluation_guide: question.evaluation_guide,
      })),
      scoring_dimensions: round.scoring_dimensions.map((dimension) => ({
        name: dimension.name,
        description: dimension.description,
        weight_percent: dimension.weight_percent,
        anchors: anchorScores.map((score) => ({
          score_value: score,
          description:
            dimension.anchors.find((anchor) => anchor.score_value === score)?.description ?? '',
        })),
      })),
    })),
  }
}

function toDraftPayload(values: InterviewPlanFormValues): InterviewPlanDraftInput {
  return {
    rounds: (values.rounds ?? []).map((round, roundIndex) => ({
      name: round.name?.trim() ?? '',
      round_type: round.round_type ?? 'technical',
      duration_minutes: round.duration_minutes ?? 60,
      pass_threshold: round.pass_threshold ?? 60,
      focus: round.focus?.trim() ?? '',
      sort_order: roundIndex,
      questions: (round.questions ?? []).map((question, questionIndex) => ({
        question_text: question.question_text?.trim() ?? '',
        evaluation_guide: question.evaluation_guide?.trim() ?? '',
        sort_order: questionIndex,
      })),
      scoring_dimensions: (round.scoring_dimensions ?? []).map(
        (dimension, dimensionIndex) => ({
          name: dimension.name?.trim() ?? '',
          description: dimension.description?.trim() ?? '',
          weight_percent: dimension.weight_percent ?? 0,
          sort_order: dimensionIndex,
          anchors: (dimension.anchors ?? [])
            .filter((anchor) => anchor.description?.trim())
            .map((anchor) => ({
              score_value: anchor.score_value,
              description: anchor.description.trim(),
            })),
        }),
      ),
    })),
  }
}

function confirmValidationError(payload: InterviewPlanDraftInput): string | null {
  if (!payload.rounds.length) return '至少需要一个面试轮次'
  for (const round of payload.rounds) {
    if (!round.questions.length) return `${round.name}至少需要一个面试问题`
    if (!round.scoring_dimensions.length) return `${round.name}至少需要一个评分维度`
    const totalWeight = round.scoring_dimensions.reduce(
      (total, dimension) => total + Number(dimension.weight_percent ?? 0),
      0,
    )
    if (totalWeight !== 100) {
      return `${round.name}评分维度权重总和必须为 100%，当前为 ${totalWeight}%`
    }
    for (const dimension of round.scoring_dimensions) {
      if (dimension.anchors.length !== 5) {
        return `${round.name}的${dimension.name}必须完整填写 1～5 分评分锚点`
      }
    }
  }
  return null
}

function DraftInterviewPlanEditor({
  jobId,
  version,
  disabled,
}: {
  jobId: string
  version: InterviewPlanVersion
  disabled: boolean
}) {
  const queryClient = useQueryClient()
  const [form] = Form.useForm<InterviewPlanFormValues>()
  const [messageApi, contextHolder] = message.useMessage()
  const rounds = Form.useWatch('rounds', form) ?? []
  const saveMutation = useMutation({
    mutationFn: (payload: InterviewPlanDraftInput) =>
      updateInterviewPlanDraft(jobId, version.id, payload),
  })
  const confirmMutation = useMutation({
    mutationFn: () => confirmInterviewPlanVersion(jobId, version.id),
  })

  useEffect(() => {
    form.setFieldsValue(versionToForm(version))
  }, [form, version])

  async function refreshVersions() {
    await queryClient.invalidateQueries({ queryKey: ['interview-plans', jobId] })
  }

  async function handleSave() {
    try {
      const values = form.getFieldsValue(true)
      await saveMutation.mutateAsync(toDraftPayload(values))
      await refreshVersions()
      messageApi.success('面试方案草稿已保存')
    } catch (error) {
      messageApi.error(errorMessage(error, '保存面试方案失败'))
    }
  }

  async function handleConfirm() {
    try {
      const values = await form.validateFields()
      const payload = toDraftPayload(values)
      const validationError = confirmValidationError(payload)
      if (validationError) {
        messageApi.error(validationError)
        return
      }
      await saveMutation.mutateAsync(payload)
      await confirmMutation.mutateAsync()
      await refreshVersions()
      messageApi.success(`面试方案 V${version.version_number} 已确认并锁定`)
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) return
      messageApi.error(errorMessage(error, '确认面试方案失败'))
    }
  }

  return (
    <>
      {contextHolder}
      <Form
        form={form}
        layout="vertical"
        className="criteria-form interview-plan-form"
        disabled={disabled}
        initialValues={{ rounds: [] }}
      >
        <Alert
          type="info"
          showIcon
          className="page-alert"
          message="草稿可以分步保存；确认时每轮必须具有问题、权重合计 100% 的评分维度和完整 1～5 分锚点。"
        />
        <Form.List name="rounds">
          {(roundFields, { add: addRound, remove: removeRound, move: moveRound }) => (
            <Space direction="vertical" size="large" className="dynamic-list">
              {roundFields.map((roundField, roundIndex) => {
                const dimensions = rounds[roundIndex]?.scoring_dimensions ?? []
                const totalWeight = dimensions.reduce(
                  (total, item) => total + Number(item?.weight_percent ?? 0),
                  0,
                )
                return (
                  <Card
                    key={roundField.key}
                    className="criteria-section interview-round-card"
                    title={`面试轮次 ${roundIndex + 1}`}
                    extra={!disabled ? (
                      <Space size="small">
                        <Button
                          aria-label={`上移面试轮次 ${roundIndex + 1}`}
                          icon={<ArrowUpOutlined />}
                          disabled={disabled || roundIndex === 0}
                          onClick={() => moveRound(roundIndex, roundIndex - 1)}
                        />
                        <Button
                          aria-label={`下移面试轮次 ${roundIndex + 1}`}
                          icon={<ArrowDownOutlined />}
                          disabled={disabled || roundIndex === roundFields.length - 1}
                          onClick={() => moveRound(roundIndex, roundIndex + 1)}
                        />
                        <Button
                          danger
                          aria-label={`删除面试轮次 ${roundIndex + 1}`}
                          icon={<DeleteOutlined />}
                          disabled={disabled}
                          onClick={() => removeRound(roundField.name)}
                        />
                      </Space>
                    ) : undefined}
                  >
                    <div className="interview-round-grid">
                      <Form.Item
                        label="轮次名称"
                        name={[roundField.name, 'name']}
                        rules={[{ required: true, whitespace: true, message: '请输入轮次名称' }]}
                      >
                        <Input
                          aria-label={`面试轮次 ${roundIndex + 1} 名称`}
                          placeholder="例如：技术一面"
                        />
                      </Form.Item>
                      <Form.Item
                        label="轮次类型"
                        name={[roundField.name, 'round_type']}
                        rules={[{ required: true, message: '请选择轮次类型' }]}
                      >
                        <Select
                          aria-label={`面试轮次 ${roundIndex + 1} 类型`}
                          options={roundTypeOptions}
                        />
                      </Form.Item>
                      <Form.Item
                        label="建议时长"
                        name={[roundField.name, 'duration_minutes']}
                        rules={[{ required: true, message: '请输入建议时长' }]}
                      >
                        <InputNumber
                          aria-label={`面试轮次 ${roundIndex + 1} 建议时长`}
                          min={15}
                          max={480}
                          suffix="分钟"
                        />
                      </Form.Item>
                      <Form.Item
                        label="通过线"
                        name={[roundField.name, 'pass_threshold']}
                        rules={[{ required: true, message: '请输入通过线' }]}
                      >
                        <InputNumber
                          aria-label={`面试轮次 ${roundIndex + 1} 通过线`}
                          min={0}
                          max={100}
                          suffix="分"
                        />
                      </Form.Item>
                    </div>
                    <Form.Item label="考察重点" name={[roundField.name, 'focus']}>
                      <Input.TextArea
                        aria-label={`面试轮次 ${roundIndex + 1} 考察重点`}
                        rows={2}
                        placeholder="说明本轮需要重点验证的能力、经历与风险"
                      />
                    </Form.Item>

                    <Card title="面试问题" size="small" className="interview-subsection">
                      <Form.List name={[roundField.name, 'questions']}>
                        {(questionFields, { add, remove, move }) => (
                          <Space direction="vertical" size="middle" className="dynamic-list">
                            {questionFields.map((questionField, questionIndex) => (
                              <Card
                                key={questionField.key}
                                size="small"
                                title={`问题 ${questionIndex + 1}`}
                                extra={!disabled ? (
                                  <Space size="small">
                                    <Button
                                      aria-label={`上移轮次 ${roundIndex + 1} 问题 ${questionIndex + 1}`}
                                      icon={<ArrowUpOutlined />}
                                      disabled={disabled || questionIndex === 0}
                                      onClick={() => move(questionIndex, questionIndex - 1)}
                                    />
                                    <Button
                                      aria-label={`下移轮次 ${roundIndex + 1} 问题 ${questionIndex + 1}`}
                                      icon={<ArrowDownOutlined />}
                                      disabled={
                                        disabled || questionIndex === questionFields.length - 1
                                      }
                                      onClick={() => move(questionIndex, questionIndex + 1)}
                                    />
                                    <Button
                                      danger
                                      aria-label={`删除轮次 ${roundIndex + 1} 问题 ${questionIndex + 1}`}
                                      icon={<DeleteOutlined />}
                                      disabled={disabled}
                                      onClick={() => remove(questionField.name)}
                                    />
                                  </Space>
                                ) : undefined}
                              >
                                <Form.Item
                                  label="问题正文"
                                  name={[questionField.name, 'question_text']}
                                  rules={[
                                    { required: true, whitespace: true, message: '请输入面试问题' },
                                  ]}
                                >
                                  <Input.TextArea
                                    aria-label={`轮次 ${roundIndex + 1} 问题 ${questionIndex + 1} 正文`}
                                    rows={2}
                                  />
                                </Form.Item>
                                <Form.Item
                                  label="评价参考要点"
                                  name={[questionField.name, 'evaluation_guide']}
                                >
                                  <Input.TextArea
                                    aria-label={`轮次 ${roundIndex + 1} 问题 ${questionIndex + 1} 评价参考要点`}
                                    rows={2}
                                  />
                                </Form.Item>
                              </Card>
                            ))}
                            {!disabled && <Button
                              type="dashed"
                              block
                              icon={<PlusOutlined />}
                              disabled={disabled}
                              onClick={() => add({ question_text: '', evaluation_guide: '' })}
                            >
                              添加面试问题
                            </Button>}
                          </Space>
                        )}
                      </Form.List>
                    </Card>

                    <Card
                      title="结构化评分表"
                      size="small"
                      className="interview-subsection"
                      extra={
                        <Tag color={totalWeight === 100 ? 'success' : 'warning'}>
                          当前权重 {totalWeight}%
                        </Tag>
                      }
                    >
                      <Form.List name={[roundField.name, 'scoring_dimensions']}>
                        {(dimensionFields, { add, remove, move }) => (
                          <Space direction="vertical" size="middle" className="dynamic-list">
                            {dimensionFields.map((dimensionField, dimensionIndex) => (
                              <Card
                                key={dimensionField.key}
                                size="small"
                                title={`评分维度 ${dimensionIndex + 1}`}
                                extra={!disabled ? (
                                  <Space size="small">
                                    <Button
                                      aria-label={`上移轮次 ${roundIndex + 1} 评分维度 ${dimensionIndex + 1}`}
                                      icon={<ArrowUpOutlined />}
                                      disabled={disabled || dimensionIndex === 0}
                                      onClick={() => move(dimensionIndex, dimensionIndex - 1)}
                                    />
                                    <Button
                                      aria-label={`下移轮次 ${roundIndex + 1} 评分维度 ${dimensionIndex + 1}`}
                                      icon={<ArrowDownOutlined />}
                                      disabled={
                                        disabled || dimensionIndex === dimensionFields.length - 1
                                      }
                                      onClick={() => move(dimensionIndex, dimensionIndex + 1)}
                                    />
                                    <Button
                                      danger
                                      aria-label={`删除轮次 ${roundIndex + 1} 评分维度 ${dimensionIndex + 1}`}
                                      icon={<DeleteOutlined />}
                                      disabled={disabled}
                                      onClick={() => remove(dimensionField.name)}
                                    />
                                  </Space>
                                ) : undefined}
                              >
                                <div className="criteria-dimension-grid">
                                  <Form.Item
                                    label="维度名称"
                                    name={[dimensionField.name, 'name']}
                                    rules={[
                                      {
                                        required: true,
                                        whitespace: true,
                                        message: '请输入维度名称',
                                      },
                                    ]}
                                  >
                                    <Input
                                      aria-label={`轮次 ${roundIndex + 1} 评分维度 ${dimensionIndex + 1} 名称`}
                                    />
                                  </Form.Item>
                                  <Form.Item
                                    label="权重"
                                    name={[dimensionField.name, 'weight_percent']}
                                    rules={[{ required: true, message: '请输入权重' }]}
                                  >
                                    <InputNumber
                                      aria-label={`轮次 ${roundIndex + 1} 评分维度 ${dimensionIndex + 1} 权重`}
                                      min={0}
                                      max={100}
                                      suffix="%"
                                    />
                                  </Form.Item>
                                </div>
                                <Form.Item
                                  label="评分说明"
                                  name={[dimensionField.name, 'description']}
                                >
                                  <Input.TextArea
                                    aria-label={`轮次 ${roundIndex + 1} 评分维度 ${dimensionIndex + 1} 说明`}
                                    rows={2}
                                  />
                                </Form.Item>
                                <Paragraph type="secondary">1 分代表明显不足，5 分代表显著超出要求。</Paragraph>
                                <Form.List name={[dimensionField.name, 'anchors']}>
                                  {(anchorFields) => (
                                    <div className="interview-anchor-grid">
                                      {anchorFields.map((anchorField, anchorIndex) => (
                                        <div key={anchorField.key}>
                                          <Form.Item
                                            name={[anchorField.name, 'score_value']}
                                            hidden
                                          >
                                            <InputNumber />
                                          </Form.Item>
                                          <Form.Item
                                            label={`${anchorIndex + 1} 分锚点`}
                                            name={[anchorField.name, 'description']}
                                          >
                                            <Input.TextArea
                                              aria-label={`轮次 ${roundIndex + 1} 评分维度 ${dimensionIndex + 1} ${anchorIndex + 1} 分锚点`}
                                              rows={2}
                                            />
                                          </Form.Item>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </Form.List>
                              </Card>
                            ))}
                            {!disabled && <Button
                              type="dashed"
                              block
                              icon={<PlusOutlined />}
                              disabled={disabled}
                              onClick={() =>
                                add({
                                  name: '',
                                  description: '',
                                  weight_percent: 0,
                                  anchors: emptyAnchors(),
                                })
                              }
                            >
                              添加评分维度
                            </Button>}
                          </Space>
                        )}
                      </Form.List>
                    </Card>
                  </Card>
                )
              })}
              {!disabled && <Button
                type="dashed"
                block
                icon={<PlusOutlined />}
                disabled={disabled}
                onClick={() =>
                  addRound({
                    name: '',
                    round_type: 'technical',
                    duration_minutes: 60,
                    pass_threshold: 60,
                    focus: '',
                    questions: [],
                    scoring_dimensions: [],
                  })
                }
              >
                添加面试轮次
              </Button>}
            </Space>
          )}
        </Form.List>

        {!disabled && <div className="sticky-actions">
          <Space wrap>
            <Button
              icon={<SaveOutlined />}
              disabled={disabled}
              loading={saveMutation.isPending}
              onClick={() => void handleSave()}
            >
              保存草稿
            </Button>
            <Popconfirm
              title={`确认面试方案 V${version.version_number}？`}
              description="确认后该版本不可修改；后续调整需要创建新版本。"
              okText="确认并锁定"
              cancelText="继续编辑"
              onConfirm={() => void handleConfirm()}
            >
              <Button
                type="primary"
                icon={<CheckOutlined />}
                disabled={disabled}
                loading={confirmMutation.isPending}
              >
                确认方案
              </Button>
            </Popconfirm>
          </Space>
        </div>}
      </Form>
    </>
  )
}

function ConfirmedInterviewPlanView({ version }: { version: InterviewPlanVersion }) {
  return (
    <Space direction="vertical" size="large" className="confirmed-criteria">
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
        <Descriptions.Item label="方案版本">V{version.version_number}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color="success">已确认</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="面试轮次">{version.rounds.length} 轮</Descriptions.Item>
        <Descriptions.Item label="确认时间">
          {version.confirmed_at ? new Date(version.confirmed_at).toLocaleString('zh-CN') : '-'}
        </Descriptions.Item>
      </Descriptions>

      {version.rounds.map((round, roundIndex) => (
        <Card
          key={round.id}
          title={`${roundIndex + 1}. ${round.name}`}
          extra={<Tag color="blue">{roundTypeLabels[round.round_type]}</Tag>}
          className="criteria-section"
        >
          <Descriptions size="small" column={{ xs: 1, sm: 3 }}>
            <Descriptions.Item label="建议时长">{round.duration_minutes} 分钟</Descriptions.Item>
            <Descriptions.Item label="通过线">{round.pass_threshold} 分</Descriptions.Item>
            <Descriptions.Item label="评分维度">
              {round.scoring_dimensions.length} 个
            </Descriptions.Item>
          </Descriptions>
          <Paragraph>{round.focus || '未填写考察重点'}</Paragraph>

          <Card title="面试问题" size="small" className="interview-subsection">
            <List
              dataSource={round.questions}
              renderItem={(question, index) => (
                <List.Item>
                  <List.Item.Meta
                    title={`${index + 1}. ${question.question_text}`}
                    description={question.evaluation_guide || '未填写评价参考要点'}
                  />
                </List.Item>
              )}
            />
          </Card>

          <Card title="结构化评分表" size="small" className="interview-subsection">
            <List
              dataSource={round.scoring_dimensions}
              renderItem={(dimension) => (
                <List.Item className="interview-dimension-view">
                  <div className="interview-dimension-summary">
                    <div>
                      <Text strong>{dimension.name}</Text>
                      <Paragraph type="secondary">
                        {dimension.description || '未填写评分说明'}
                      </Paragraph>
                    </div>
                    <Progress
                      percent={dimension.weight_percent}
                      size="small"
                      format={() => `${dimension.weight_percent}%`}
                    />
                  </div>
                  <div className="interview-anchor-view">
                    {dimension.anchors.map((anchor) => (
                      <div key={anchor.id}>
                        <Tag color={anchor.score_value >= 4 ? 'success' : undefined}>
                          {anchor.score_value} 分
                        </Tag>
                        <Text>{anchor.description}</Text>
                      </div>
                    ))}
                  </div>
                </List.Item>
              )}
            />
          </Card>
        </Card>
      ))}
    </Space>
  )
}

export function InterviewPlanPage() {
  const { jobId } = useParams()
  const auth = useAuth()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null)
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
  })
  const plans = useQuery({
    queryKey: ['interview-plans', jobId],
    queryFn: () => fetchInterviewPlanVersions(jobId!),
    enabled: Boolean(jobId),
  })
  const versions = useMemo(
    () => [...(plans.data ?? [])].sort((left, right) => right.version_number - left.version_number),
    [plans.data],
  )
  const selectedVersion =
    versions.find((version) => version.id === selectedVersionId) ?? versions[0]
  const createMutation = useMutation({
    mutationFn: (sourceVersionId?: string) =>
      createInterviewPlanVersion(jobId!, sourceVersionId),
    onSuccess: async (version) => {
      await queryClient.invalidateQueries({ queryKey: ['interview-plans', jobId] })
      setSelectedVersionId(version.id)
      messageApi.success(`已创建面试方案草稿 V${version.version_number}`)
    },
    onError: (error) => messageApi.error(errorMessage(error, '创建面试方案版本失败')),
  })

  useEffect(() => {
    if (versions.length > 0 && !versions.some((item) => item.id === selectedVersionId)) {
      const draft = versions.find((item) => item.status === 'draft')
      setSelectedVersionId((draft ?? versions[0]).id)
    }
  }, [selectedVersionId, versions])

  if (job.isPending || plans.isPending) return <Skeleton active paragraph={{ rows: 12 }} />

  if (job.isError || !job.data || plans.isError) {
    return (
      <Alert
        type="error"
        showIcon
        message="无法读取职位面试方案"
        description={job.error?.message ?? plans.error?.message}
        action={
          <Button
            onClick={() => {
              void job.refetch()
              void plans.refetch()
            }}
          >
            重试
          </Button>
        }
      />
    )
  }

  const archived = job.data.status === 'archived'
  const canWrite = canManageRecruitment(auth.user) && !archived

  return (
    <>
      {contextHolder}
      <div className="page-heading">
        <div>
          <Space size="small" wrap>
            <Title level={2}>{job.data.title}</Title>
            {archived && <Tag>已归档</Tag>}
          </Space>
          <Text type="secondary">
            {job.data.department || '未填写部门'} · 配置面试轮次、问题和结构化评分表
          </Text>
        </div>
      </div>

      {!canWrite && (
        <Alert
          type="warning"
          showIcon
          message={archived ? '该职位已归档，面试方案仅供查看' : '当前角色可查看面试方案，但不能修改'}
          className="page-alert"
        />
      )}

      {versions.length === 0 ? (
        <section className="empty-workspace">
          <Empty description="尚未建立面试方案">
            {canWrite && <Button
              type="primary"
              icon={<PlusOutlined />}
              loading={createMutation.isPending}
              onClick={() => createMutation.mutate(undefined)}
            >
              创建面试方案草稿
            </Button>}
          </Empty>
        </section>
      ) : (
        <div className="criteria-layout">
          <main className="criteria-main">
            <div className="criteria-version-heading">
              <div>
                <Title level={3}>面试方案 V{selectedVersion.version_number}</Title>
                <Text type="secondary">
                  {selectedVersion.status === 'draft' ? '草稿可继续编辑' : '已确认版本不可修改'}
                </Text>
              </div>
              <Space>
                <Tag color={selectedVersion.status === 'draft' ? 'processing' : 'success'}>
                  {selectedVersion.status === 'draft' ? '草稿' : '已确认'}
                </Tag>
                {selectedVersion.status === 'confirmed' && canWrite && (
                  <Button
                    icon={<CopyOutlined />}
                    loading={createMutation.isPending}
                    onClick={() => createMutation.mutate(selectedVersion.id)}
                  >
                    基于此版本新建
                  </Button>
                )}
              </Space>
            </div>

            {selectedVersion.status === 'draft' ? (
              <DraftInterviewPlanEditor
                jobId={jobId!}
                version={selectedVersion}
                disabled={!canWrite}
              />
            ) : (
              <ConfirmedInterviewPlanView version={selectedVersion} />
            )}
          </main>

          <aside className="version-history" aria-label="面试方案版本历史">
            <Card title="版本历史" size="small">
              <Space direction="vertical" className="version-list">
                {versions.map((version) => (
                  <button
                    type="button"
                    key={version.id}
                    className={`version-item ${selectedVersion.id === version.id ? 'is-selected' : ''}`}
                    onClick={() => setSelectedVersionId(version.id)}
                  >
                    <span>
                      <strong>V{version.version_number}</strong>
                      <small>
                        {version.rounds.length} 个轮次 ·{' '}
                        {version.rounds.reduce(
                          (total, round) => total + round.questions.length,
                          0,
                        )}{' '}
                        个问题
                      </small>
                    </span>
                    <Tag color={version.status === 'draft' ? 'processing' : 'success'}>
                      {version.status === 'draft' ? '草稿' : '已确认'}
                    </Tag>
                  </button>
                ))}
              </Space>
            </Card>
          </aside>
        </div>
      )}
    </>
  )
}
