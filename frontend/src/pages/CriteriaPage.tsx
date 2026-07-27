import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CheckOutlined,
  CopyOutlined,
  DeleteOutlined,
  PlusOutlined,
  RobotOutlined,
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
  Switch,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  ApiError,
  confirmCriteriaVersion,
  createCriteriaVersion,
  fetchJob,
  generateJDAIDraft,
  updateCriteriaDraft,
  type CriteriaDraftInput,
  type CriteriaVersion,
  type HardRequirementInput,
  type HardRequirementType,
  type JDAIDraft,
  type ScoringDimensionInput,
} from '../api/client'
import { useAuth } from '../auth/context'
import { canManageRecruitment } from '../auth/permissions'
import { ScreeningModuleNav } from '../components/ScreeningModuleNav'

const { Title, Text, Paragraph } = Typography

const requirementTypeOptions: Array<{ label: string; value: HardRequirementType }> = [
  { label: '最低相关经验年限', value: 'min_experience_years' },
  { label: '最低学历', value: 'min_education' },
  { label: '必需证书或执照', value: 'required_certification' },
  { label: '明确语言等级', value: 'language_level' },
  { label: '其他人工核对条件', value: 'other' },
]

interface CriteriaFormValues {
  pass_threshold: number
  hard_requirements: HardRequirementInput[]
  scoring_dimensions: ScoringDimensionInput[]
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback
}

function toDraftPayload(values: CriteriaFormValues): CriteriaDraftInput {
  return {
    pass_threshold: values.pass_threshold,
    hard_requirements: (values.hard_requirements ?? []).map((item, index) => ({
      requirement_type: item.requirement_type,
      title: item.title.trim(),
      description: item.description?.trim() ?? '',
      expected_value: item.expected_value.trim(),
      auto_reject: item.auto_reject ?? false,
      sort_order: index,
    })),
    scoring_dimensions: (values.scoring_dimensions ?? []).map((item, index) => ({
      name: item.name.trim(),
      description: item.description?.trim() ?? '',
      weight_percent: item.weight_percent,
      sort_order: index,
    })),
  }
}

function DraftCriteriaEditor({
  jobId,
  version,
  disabled,
}: {
  jobId: string
  version: CriteriaVersion
  disabled: boolean
}) {
  const queryClient = useQueryClient()
  const [form] = Form.useForm<CriteriaFormValues>()
  const [messageApi, contextHolder] = message.useMessage()
  const [aiDraft, setAiDraft] = useState<JDAIDraft | null>(null)
  const dimensions = Form.useWatch('scoring_dimensions', form) ?? []
  const totalWeight = dimensions.reduce(
    (total, item) => total + Number(item?.weight_percent ?? 0),
    0,
  )
  const saveMutation = useMutation({
    mutationFn: (payload: CriteriaDraftInput) =>
      updateCriteriaDraft(jobId, version.id, payload),
  })
  const confirmMutation = useMutation({
    mutationFn: () => confirmCriteriaVersion(jobId, version.id),
  })
  const aiDraftMutation = useMutation({
    mutationFn: () => generateJDAIDraft(jobId),
    onSuccess: (draft) => {
      form.setFieldsValue({
        pass_threshold: draft.pass_threshold,
        hard_requirements: draft.hard_requirements.map((item) => ({ ...item })),
        scoring_dimensions: draft.scoring_dimensions.map((item) => ({ ...item })),
      })
      setAiDraft(draft)
      messageApi.success('AI 草稿已填入，请核对后保存或确认')
    },
    onError: (error) => messageApi.error(errorMessage(error, 'AI 生成筛选草稿失败')),
  })

  useEffect(() => {
    form.setFieldsValue({
      pass_threshold: version.pass_threshold,
      hard_requirements: version.hard_requirements.map((item) => ({ ...item })),
      scoring_dimensions: version.scoring_dimensions.map((item) => ({ ...item })),
    })
  }, [form, version])

  async function refreshJob() {
    await queryClient.invalidateQueries({ queryKey: ['job', jobId] })
    await queryClient.invalidateQueries({ queryKey: ['jobs'] })
  }

  async function handleSave() {
    try {
      const values = await form.validateFields()
      await saveMutation.mutateAsync(toDraftPayload(values))
      await refreshJob()
      messageApi.success('筛选标准草稿已保存')
    } catch (error) {
      if (error instanceof ApiError) {
        messageApi.error(error.message)
      }
    }
  }

  async function handleConfirm() {
    try {
      const values = await form.validateFields()
      if (!values.scoring_dimensions?.length) {
        messageApi.error('至少需要一个评分维度')
        return
      }
      const payload = toDraftPayload(values)
      const weight = payload.scoring_dimensions.reduce(
        (total, item) => total + item.weight_percent,
        0,
      )
      if (weight !== 100) {
        messageApi.error(`评分维度权重总和必须为 100%，当前为 ${weight}%`)
        return
      }
      await saveMutation.mutateAsync(payload)
      await confirmMutation.mutateAsync()
      await refreshJob()
      messageApi.success(`标准版本 V${version.version_number} 已确认`)
    } catch (error) {
      if (error instanceof ApiError) {
        messageApi.error(error.message)
      }
    }
  }

  return (
    <>
      {contextHolder}
      <Form<CriteriaFormValues>
        form={form}
        layout="vertical"
        requiredMark={false}
        disabled={disabled}
        className="criteria-form"
      >
        {!disabled && <Card className="criteria-section ai-draft-card">
          <div className="ai-draft-heading">
            <div>
              <Title level={4}>AI 辅助生成筛选草稿</Title>
              <Paragraph type="secondary">
                AI 只会填入当前表单，不会自动保存或确认。请逐项核对硬性要求、权重和判断边界。
              </Paragraph>
            </div>
            <Popconfirm
              title="使用 AI 生成并替换当前表单？"
              description="当前尚未保存的编辑会被 AI 草稿替换。"
              okText="生成并替换"
              cancelText="取消"
              onConfirm={() => aiDraftMutation.mutate()}
            >
              <Button
                type="primary"
                ghost
                icon={<RobotOutlined />}
                loading={aiDraftMutation.isPending}
              >
                AI 生成草稿
              </Button>
            </Popconfirm>
          </div>
          {aiDraft && (
            <Alert
              type="info"
              showIcon
              message={`建议职位名称：${aiDraft.suggested_title}`}
              description={aiDraft.summary}
            />
          )}
        </Card>}

        <Card
          title="基本评分规则"
          extra={
            <Tag color={totalWeight === 100 ? 'success' : 'warning'}>
              当前权重 {totalWeight}%
            </Tag>
          }
          className="criteria-section"
        >
          <Form.Item
            label="语义匹配通过线"
            name="pass_threshold"
            rules={[{ required: true, message: '请设置通过线' }]}
            extra="低于通过线只标记为低匹配，不会自动淘汰。"
          >
            <InputNumber min={0} max={100} suffix="分" />
          </Form.Item>
        </Card>

        <Card title="硬性要求" className="criteria-section">
          <Paragraph type="secondary">
            信息缺失必须标记待确认。只有经验、学历、证书和语言等级可开启自动淘汰。
          </Paragraph>
          <Form.List name="hard_requirements">
            {(fields, { add, remove, move }) => (
              <Space direction="vertical" size="middle" className="dynamic-list">
                {fields.map((field, index) => (
                  <Card
                    size="small"
                    key={field.key}
                    title={`硬性要求 ${index + 1}`}
                    extra={!disabled ? (
                      <Space size="small">
                        <Button
                          aria-label={`上移硬性要求 ${index + 1}`}
                          icon={<ArrowUpOutlined />}
                          disabled={index === 0}
                          onClick={() => move(index, index - 1)}
                        />
                        <Button
                          aria-label={`下移硬性要求 ${index + 1}`}
                          icon={<ArrowDownOutlined />}
                          disabled={index === fields.length - 1}
                          onClick={() => move(index, index + 1)}
                        />
                        <Button
                          danger
                          aria-label={`删除硬性要求 ${index + 1}`}
                          icon={<DeleteOutlined />}
                          onClick={() => remove(field.name)}
                        />
                      </Space>
                    ) : undefined}
                  >
                    <div className="criteria-field-grid">
                      <Form.Item
                        label="条件类型"
                        name={[field.name, 'requirement_type']}
                        rules={[{ required: true, message: '请选择条件类型' }]}
                      >
                        <Select
                          options={requirementTypeOptions}
                          onChange={(value: HardRequirementType) => {
                            if (value === 'other') {
                              form.setFieldValue(
                                ['hard_requirements', field.name, 'auto_reject'],
                                false,
                              )
                            }
                          }}
                        />
                      </Form.Item>
                      <Form.Item
                        label="要求名称"
                        name={[field.name, 'title']}
                        rules={[{ required: true, whitespace: true, message: '请输入要求名称' }]}
                      >
                        <Input placeholder="例如：相关工作经验" />
                      </Form.Item>
                      <Form.Item
                        label="期望值"
                        name={[field.name, 'expected_value']}
                        rules={[{ required: true, whitespace: true, message: '请输入期望值' }]}
                      >
                        <Input placeholder="例如：3 年" />
                      </Form.Item>
                      <Form.Item noStyle shouldUpdate>
                        {({ getFieldValue }) => {
                          const requirementType = getFieldValue([
                            'hard_requirements',
                            field.name,
                            'requirement_type',
                          ]) as HardRequirementType | undefined
                          return (
                            <Form.Item
                              label="明确不满足时自动淘汰"
                              name={[field.name, 'auto_reject']}
                              valuePropName="checked"
                            >
                              <Switch disabled={requirementType === 'other'} />
                            </Form.Item>
                          )
                        }}
                      </Form.Item>
                    </div>
                    <Form.Item label="判断说明" name={[field.name, 'description']}>
                      <Input.TextArea rows={2} placeholder="说明如何判断满足、缺失或不满足" />
                    </Form.Item>
                  </Card>
                ))}
                {!disabled && <Button
                  type="dashed"
                  block
                  icon={<PlusOutlined />}
                  onClick={() =>
                    add({
                      requirement_type: 'min_experience_years',
                      title: '',
                      expected_value: '',
                      description: '',
                      auto_reject: false,
                    })
                  }
                >
                  添加硬性要求
                </Button>}
              </Space>
            )}
          </Form.List>
        </Card>

        <Card title="评分维度" className="criteria-section">
          <Paragraph type="secondary">确认前所有评分维度权重总和必须为 100%。</Paragraph>
          <Form.List name="scoring_dimensions">
            {(fields, { add, remove, move }) => (
              <Space direction="vertical" size="middle" className="dynamic-list">
                {fields.map((field, index) => (
                  <Card
                    size="small"
                    key={field.key}
                    title={`评分维度 ${index + 1}`}
                    extra={!disabled ? (
                      <Space size="small">
                        <Button
                          aria-label={`上移评分维度 ${index + 1}`}
                          icon={<ArrowUpOutlined />}
                          disabled={index === 0}
                          onClick={() => move(index, index - 1)}
                        />
                        <Button
                          aria-label={`下移评分维度 ${index + 1}`}
                          icon={<ArrowDownOutlined />}
                          disabled={index === fields.length - 1}
                          onClick={() => move(index, index + 1)}
                        />
                        <Button
                          danger
                          aria-label={`删除评分维度 ${index + 1}`}
                          icon={<DeleteOutlined />}
                          onClick={() => remove(field.name)}
                        />
                      </Space>
                    ) : undefined}
                  >
                    <div className="criteria-dimension-grid">
                      <Form.Item
                        label="维度名称"
                        name={[field.name, 'name']}
                        rules={[{ required: true, whitespace: true, message: '请输入维度名称' }]}
                      >
                        <Input placeholder="例如：后端系统设计" />
                      </Form.Item>
                      <Form.Item
                        label="权重"
                        name={[field.name, 'weight_percent']}
                        rules={[{ required: true, message: '请输入权重' }]}
                      >
                        <InputNumber min={0} max={100} suffix="%" />
                      </Form.Item>
                    </div>
                    <Form.Item label="评分说明" name={[field.name, 'description']}>
                      <Input.TextArea rows={2} placeholder="说明该维度关注的经历、能力和证据" />
                    </Form.Item>
                  </Card>
                ))}
                {!disabled && <Button
                  type="dashed"
                  block
                  icon={<PlusOutlined />}
                  onClick={() => add({ name: '', description: '', weight_percent: 0 })}
                >
                  添加评分维度
                </Button>}
              </Space>
            )}
          </Form.List>
        </Card>

        {!disabled && <div className="sticky-actions">
          <Space wrap>
            <Button
              icon={<SaveOutlined />}
              loading={saveMutation.isPending}
              onClick={() => void handleSave()}
            >
              保存草稿
            </Button>
            <Popconfirm
              title={`确认标准版本 V${version.version_number}？`}
              description="确认后该版本不可修改；后续调整会创建新版本。"
              okText="确认并锁定"
              cancelText="继续编辑"
              onConfirm={() => void handleConfirm()}
            >
              <Button
                type="primary"
                icon={<CheckOutlined />}
                loading={confirmMutation.isPending}
              >
                确认标准
              </Button>
            </Popconfirm>
          </Space>
        </div>}
      </Form>
    </>
  )
}

function ConfirmedCriteriaView({ version }: { version: CriteriaVersion }) {
  return (
    <Space direction="vertical" size="large" className="confirmed-criteria">
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
        <Descriptions.Item label="版本">V{version.version_number}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color="success">已确认</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="语义通过线">{version.pass_threshold} 分</Descriptions.Item>
        <Descriptions.Item label="确认时间">
          {version.confirmed_at ? new Date(version.confirmed_at).toLocaleString('zh-CN') : '-'}
        </Descriptions.Item>
      </Descriptions>

      <Card title="硬性要求" size="small">
        {version.hard_requirements.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未配置硬性要求" />
        ) : (
          <List
            dataSource={version.hard_requirements}
            renderItem={(item) => (
              <List.Item>
                <List.Item.Meta title={item.title} description={item.description || item.expected_value} />
                <Space>
                  <Text>{item.expected_value}</Text>
                  {item.auto_reject && <Tag color="error">允许自动淘汰</Tag>}
                </Space>
              </List.Item>
            )}
          />
        )}
      </Card>

      <Card title="评分维度" size="small">
        <List
          dataSource={version.scoring_dimensions}
          renderItem={(item) => (
            <List.Item>
              <List.Item.Meta title={item.name} description={item.description || '未填写评分说明'} />
              <div className="dimension-progress">
                <Progress percent={item.weight_percent} size="small" format={() => `${item.weight_percent}%`} />
              </div>
            </List.Item>
          )}
        />
      </Card>
    </Space>
  )
}

export function CriteriaPage() {
  const { jobId } = useParams()
  const auth = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null)
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
  })
  const versions = useMemo(
    () =>
      [...(job.data?.criteria_versions ?? [])].sort(
        (left, right) => right.version_number - left.version_number,
      ),
    [job.data?.criteria_versions],
  )
  const selectedVersion =
    versions.find((version) => version.id === selectedVersionId) ?? versions[0]
  const createMutation = useMutation({
    mutationFn: (sourceVersionId?: string) => createCriteriaVersion(jobId!, sourceVersionId),
    onSuccess: async (version) => {
      await queryClient.invalidateQueries({ queryKey: ['job', jobId] })
      setSelectedVersionId(version.id)
      messageApi.success(`已创建标准草稿 V${version.version_number}`)
    },
    onError: (error) => messageApi.error(errorMessage(error, '创建标准版本失败')),
  })

  useEffect(() => {
    if (versions.length > 0 && !versions.some((item) => item.id === selectedVersionId)) {
      const draft = versions.find((item) => item.status === 'draft')
      setSelectedVersionId((draft ?? versions[0]).id)
    }
  }, [selectedVersionId, versions])

  if (job.isPending) {
    return <Skeleton active paragraph={{ rows: 12 }} />
  }

  if (job.isError || !job.data) {
    return (
      <Alert
        type="error"
        showIcon
        message="无法读取职位筛选标准"
        description={job.error?.message}
        action={<Button onClick={() => void job.refetch()}>重试</Button>}
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
            {job.data.department || '未填写部门'} · 配置硬性要求、评分维度和语义通过线
          </Text>
        </div>
        {canWrite && (
          <Button onClick={() => navigate(`/jobs/${jobId}/edit`)}>编辑职位信息</Button>
        )}
      </div>

      <ScreeningModuleNav jobId={jobId} activeKey="criteria" />

      {!canWrite && (
        <Alert
          type="warning"
          showIcon
          message={archived ? '该职位已归档，筛选标准仅供查看' : '当前角色可查看筛选标准，但不能修改'}
          className="page-alert"
        />
      )}

      {versions.length === 0 ? (
        <section className="empty-workspace">
          <Empty description="尚未建立筛选标准">
            {canWrite && <Button
              type="primary"
              icon={<PlusOutlined />}
              loading={createMutation.isPending}
              onClick={() => createMutation.mutate(undefined)}
            >
              创建筛选标准草稿
            </Button>}
          </Empty>
        </section>
      ) : (
        <div className="criteria-layout">
          <main className="criteria-main">
            <div className="criteria-version-heading">
              <div>
                <Title level={3}>标准版本 V{selectedVersion.version_number}</Title>
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
              <DraftCriteriaEditor jobId={jobId!} version={selectedVersion} disabled={!canWrite} />
            ) : (
              <ConfirmedCriteriaView version={selectedVersion} />
            )}
          </main>

          <aside className="version-history" aria-label="标准版本历史">
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
                        {version.scoring_dimensions.length} 个评分维度 ·{' '}
                        {version.hard_requirements.length} 个硬性要求
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
