import {
  ArrowLeftOutlined,
  EditOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Collapse,
  Descriptions,
  Empty,
  Input,
  List,
  Modal,
  Progress,
  Select,
  Skeleton,
  Space,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import type { ReactNode } from 'react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  ApiError,
  correctCandidateProfile,
  fetchCandidateAnalysisHistory,
  fetchCandidateProfiles,
  fetchJob,
  fetchScreeningBatches,
  reanalyzeCandidate,
  type AnalysisStatus,
  type CandidateProfileInput,
  type CandidateProfileRecord,
  type ScreeningResultDetail,
} from '../api/client'
import { useAuth } from '../auth/context'
import {
  canManageRecruitment,
  canViewSensitiveRecruitmentData,
} from '../auth/permissions'

const { Title, Text, Paragraph } = Typography

const profileSections = [
  ['education', '教育经历'],
  ['work_experiences', '工作经历'],
  ['projects', '项目经历'],
  ['skills', '技能'],
  ['certifications', '证书'],
  ['languages', '语言能力'],
] as const

type ProfileSection = (typeof profileSections)[number][0]
type EditorValues = Record<ProfileSection, string>

const analysisStatusMeta: Record<AnalysisStatus, { color: string; label: string }> = {
  processing: { color: 'processing', label: '分析中' },
  completed: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
}

function formatDate(value: string | null) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value))
}

function editorFromProfile(profile: CandidateProfileRecord): EditorValues {
  return Object.fromEntries(
    profileSections.map(([key]) => [key, JSON.stringify(profile[key], null, 2)]),
  ) as EditorValues
}

function parseProfileEditor(values: EditorValues): CandidateProfileInput {
  const parsed = {} as CandidateProfileInput
  for (const [key, label] of profileSections) {
    let value: unknown
    try {
      value = JSON.parse(values[key])
    } catch {
      throw new Error(`${label}不是有效 JSON`)
    }
    if (!Array.isArray(value)) throw new Error(`${label}必须是 JSON 数组`)
    parsed[key] = value as Record<string, unknown>[]
  }
  return parsed
}

type ProfileItem = Record<string, unknown>

function profileField(item: ProfileItem, key: string): string {
  const value = item[key]
  return typeof value === 'string' ? value.trim() : ''
}

function joinProfileFields(...values: string[]): string {
  return values.filter(Boolean).join(' · ')
}

function profileDateRange(item: ProfileItem): string {
  const start = profileField(item, 'start_date')
  const end = profileField(item, 'end_date')
  if (!start && !end) return ''
  if (!end || ['至今', 'present', 'current'].includes(end.toLowerCase())) {
    return `${start || '时间未填写'} 至今`
  }
  return `${start || '时间未填写'} 至 ${end}`
}

function ProfileEvidence({ item }: { item: ProfileItem }) {
  const evidence = Array.isArray(item.evidence)
    ? item.evidence.filter(
        (value): value is ProfileItem => Boolean(value) && typeof value === 'object',
      )
    : []
  if (!evidence.length) return null

  return (
    <Collapse
      ghost
      size="small"
      className="profile-evidence-collapse"
      items={[
        {
          key: 'evidence',
          label: `查看原文证据（${evidence.length}）`,
          children: (
            <List
              size="small"
              dataSource={evidence}
              renderItem={(reference) => (
                <List.Item>
                  <div className="profile-evidence-item">
                    <Tag>{profileField(reference, 'segment_key') || '未知片段'}</Tag>
                    <Text>{profileField(reference, 'quote') || '未提供引用内容'}</Text>
                  </div>
                </List.Item>
              )}
            />
          ),
        },
      ]}
    />
  )
}

function ProfileRecord({
  title,
  subtitle,
  summary,
  item,
  showEvidence,
}: {
  title: string
  subtitle?: ReactNode
  summary?: string
  item: ProfileItem
  showEvidence: boolean
}) {
  return (
    <div className="profile-record">
      <div className="profile-record-heading">
        <Text strong>{title}</Text>
        {subtitle && <Text type="secondary">{subtitle}</Text>}
      </div>
      {summary && <Paragraph className="profile-record-summary">{summary}</Paragraph>}
      {showEvidence && <ProfileEvidence item={item} />}
    </div>
  )
}

function ProfileSectionContent({
  section,
  items,
  showEvidence,
}: {
  section: ProfileSection
  items: ProfileItem[]
  showEvidence: boolean
}) {
  if (section === 'skills' || section === 'languages') {
    return (
      <div className="profile-tag-list">
        {items.map((item, index) => {
          const name = profileField(item, section === 'skills' ? 'name' : 'language')
          const level = profileField(item, 'level')
          return (
            <div className="profile-tag-record" key={`${name}-${index}`}>
              <Tag color={section === 'skills' ? 'blue' : 'cyan'}>
                {joinProfileFields(name || '未命名', level)}
              </Tag>
              {showEvidence && <ProfileEvidence item={item} />}
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div className="profile-record-list">
      {items.map((item, index) => {
        let title = ''
        let subtitle = ''
        let summary = ''
        if (section === 'education') {
          title = profileField(item, 'institution') || '未填写学校'
          subtitle = joinProfileFields(
            profileField(item, 'degree'),
            profileField(item, 'field_of_study'),
            profileDateRange(item),
          )
        } else if (section === 'work_experiences') {
          title = profileField(item, 'company') || '未填写公司'
          subtitle = joinProfileFields(profileField(item, 'title'), profileDateRange(item))
          summary = profileField(item, 'summary')
        } else if (section === 'projects') {
          title = profileField(item, 'name') || '未命名项目'
          subtitle = profileField(item, 'role')
          summary = profileField(item, 'summary')
        } else {
          title = profileField(item, 'name') || '未命名证书'
          subtitle = joinProfileFields(
            profileField(item, 'issuer'),
            profileField(item, 'obtained_at'),
          )
        }
        return (
          <ProfileRecord
            key={`${title}-${index}`}
            title={title}
            subtitle={subtitle}
            summary={summary}
            item={item}
            showEvidence={showEvidence}
          />
        )
      })}
    </div>
  )
}

function ProfileSnapshot({
  profile,
  showEvidence,
}: {
  profile: CandidateProfileRecord
  showEvidence: boolean
}) {
  return (
    <div className="profile-snapshot-grid">
      {profileSections.map(([key, label]) => (
        <Card key={key} size="small" title={label} className="profile-section-card">
          {profile[key].length ? (
            <ProfileSectionContent
              section={key}
              items={profile[key]}
              showEvidence={showEvidence}
            />
          ) : (
            <Text type="secondary">暂无</Text>
          )}
        </Card>
      ))}
    </div>
  )
}

function AnalysisHistoryCard({ result }: { result: ScreeningResultDetail }) {
  const status = analysisStatusMeta[result.status]
  return (
    <Card className="analysis-history-card" size="small">
      <div className="analysis-history-heading">
        <Space wrap>
          <Tag color={status.color}>{status.label}</Tag>
          <Text strong>
            标准 V{result.criteria_version_number} / 分析 V{result.analysis_version}
          </Text>
          {result.candidate_profile && (
            <Tag color={result.candidate_profile.source === 'manual' ? 'purple' : 'blue'}>
              档案 V{result.candidate_profile.version_number} ·
              {result.candidate_profile.source === 'manual' ? '人工修正' : 'AI 提取'}
            </Tag>
          )}
        </Space>
        <Text type="secondary">{formatDate(result.created_at)}</Text>
      </div>
      <Descriptions
        size="small"
        column={3}
        items={[
          {
            key: 'score',
            label: '总分',
            children: result.total_score === null ? '-' : result.total_score.toFixed(1),
          },
          { key: 'model', label: '模型', children: result.model_name },
          { key: 'prompt', label: 'Prompt', children: result.prompt_version },
        ]}
      />
      {result.status === 'failed' && (
        <Alert
          type="error"
          showIcon
          message={result.failure_message ?? '本次分析失败'}
          description="失败记录会保留，但不会覆盖此前已经完成的可用结果。"
        />
      )}
      {result.status === 'completed' && (
        <Collapse
          ghost
          items={[
            {
              key: 'details',
              label: '查看本版本评分摘要',
              children: (
                <div className="analysis-version-details">
                  {result.dimension_scores.map((dimension) => (
                    <div key={dimension.id} className="analysis-version-dimension">
                      <div>
                        <Text strong>{dimension.dimension_name}</Text>
                        <Paragraph type="secondary">{dimension.rationale}</Paragraph>
                      </div>
                      <Progress type="circle" size={52} percent={dimension.score} />
                    </div>
                  ))}
                  <List
                    size="small"
                    header={<Text strong>优势</Text>}
                    dataSource={result.strengths}
                    locale={{ emptyText: '暂无' }}
                    renderItem={(item) => <List.Item>{item}</List.Item>}
                  />
                  <List
                    size="small"
                    header={<Text strong>差距与缺失</Text>}
                    dataSource={[...result.gaps, ...result.missing_items]}
                    locale={{ emptyText: '暂无' }}
                    renderItem={(item) => <List.Item>{item}</List.Item>}
                  />
                </div>
              ),
            },
          ]}
        />
      )}
    </Card>
  )
}

export function CandidateHistoryPage() {
  const { jobId, batchId, documentId } = useParams()
  const auth = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [editingProfile, setEditingProfile] = useState<CandidateProfileRecord>()
  const [editorValues, setEditorValues] = useState<EditorValues>()
  const [criteriaVersionId, setCriteriaVersionId] = useState<string>()
  const [reanalysisOpen, setReanalysisOpen] = useState(false)
  const [polling, setPolling] = useState(false)
  const [pendingAnalysis, setPendingAnalysis] = useState<{
    criteriaVersionId: string
    analysisVersion: number
  }>()

  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
  })
  const batches = useQuery({
    queryKey: ['batches', jobId],
    queryFn: () => fetchScreeningBatches(jobId!),
    enabled: Boolean(jobId),
  })
  const profiles = useQuery({
    queryKey: ['candidate-profiles', jobId, batchId, documentId],
    queryFn: () => fetchCandidateProfiles(jobId!, batchId!, documentId!),
    enabled: Boolean(jobId && batchId && documentId),
  })
  const history = useQuery({
    queryKey: ['candidate-analysis-history', jobId, batchId, documentId],
    queryFn: () => fetchCandidateAnalysisHistory(jobId!, batchId!, documentId!),
    enabled: Boolean(jobId && batchId && documentId),
    refetchInterval: polling ? 3000 : false,
  })

  const confirmedCriteria = useMemo(
    () =>
      (job.data?.criteria_versions ?? [])
        .filter((item) => item.status === 'confirmed')
        .sort((a, b) => b.version_number - a.version_number),
    [job.data?.criteria_versions],
  )
  const latestProfile = profiles.data?.[0]
  const batch = batches.data?.find((item) => item.id === batchId)
  const document = batch?.documents.find((item) => item.id === documentId)

  useEffect(() => {
    if (criteriaVersionId || !confirmedCriteria.length || history.isPending) return
    const latestCompleted = history.data?.find((item) => item.status === 'completed')
    setCriteriaVersionId(latestCompleted?.criteria_version_id ?? confirmedCriteria[0].id)
  }, [confirmedCriteria, criteriaVersionId, history.data, history.isPending])

  useEffect(() => {
    if (!polling || !pendingAnalysis || !history.data?.length) return
    const pendingResult = history.data.find(
      (item) =>
        item.criteria_version_id === pendingAnalysis.criteriaVersionId &&
        item.analysis_version === pendingAnalysis.analysisVersion,
    )
    if (pendingResult && pendingResult.status !== 'processing') {
      setPolling(false)
      setPendingAnalysis(undefined)
    }
  }, [history.data, pendingAnalysis, polling])

  useEffect(() => {
    if (!polling) return
    const timer = window.setTimeout(() => setPolling(false), 60_000)
    return () => window.clearTimeout(timer)
  }, [polling])

  const correctionMutation = useMutation({
    mutationFn: () => {
      if (!editingProfile || !editorValues || !criteriaVersionId) {
        throw new Error('缺少修正参数')
      }
      return correctCandidateProfile(
        jobId!,
        batchId!,
        documentId!,
        editingProfile.id,
        criteriaVersionId,
        parseProfileEditor(editorValues),
      )
    },
    onSuccess: async (response) => {
      setEditingProfile(undefined)
      setEditorValues(undefined)
      setPolling(response.reanalysis.status === 'queued')
      setPendingAnalysis(
        response.reanalysis.status === 'queued'
          ? {
              criteriaVersionId: response.reanalysis.criteria_version_id,
              analysisVersion: response.reanalysis.analysis_version,
            }
          : undefined,
      )
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['candidate-profiles', jobId, batchId, documentId],
        }),
        queryClient.invalidateQueries({
          queryKey: ['candidate-analysis-history', jobId, batchId, documentId],
        }),
        queryClient.invalidateQueries({ queryKey: ['screening-results', jobId] }),
      ])
      if (response.reanalysis.status === 'queued') {
        messageApi.success(
          `档案 V${response.profile.version_number} 已保存，分析 V${response.reanalysis.analysis_version} 已排队`,
        )
      } else {
        messageApi.warning('档案修正已保存，但重新分析任务创建失败，可稍后手动重跑')
      }
    },
    onError: (error) =>
      messageApi.error(error instanceof ApiError ? error.message : error instanceof Error ? error.message : '修正失败'),
  })

  const reanalysisMutation = useMutation({
    mutationFn: () =>
      reanalyzeCandidate(
        jobId!,
        batchId!,
        documentId!,
        criteriaVersionId!,
        latestProfile?.id,
      ),
    onSuccess: async (response) => {
      setReanalysisOpen(false)
      setPolling(true)
      setPendingAnalysis({
        criteriaVersionId: response.criteria_version_id,
        analysisVersion: response.analysis_version,
      })
      await queryClient.invalidateQueries({
        queryKey: ['candidate-analysis-history', jobId, batchId, documentId],
      })
      messageApi.success(`分析 V${response.analysis_version} 已进入队列`)
    },
    onError: (error) =>
      messageApi.error(error instanceof ApiError ? error.message : '重新分析失败'),
  })

  function openEditor(profile: CandidateProfileRecord) {
    setEditingProfile(profile)
    setEditorValues(editorFromProfile(profile))
  }

  function submitCorrection() {
    try {
      if (!editorValues) throw new Error('缺少修正内容')
      parseProfileEditor(editorValues)
      correctionMutation.mutate()
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : '修正内容格式不正确')
    }
  }

  if (job.isPending || batches.isPending) return <Skeleton active paragraph={{ rows: 12 }} />
  if (job.isError || batches.isError || !job.data || !document) {
    return (
      <Alert
        type="error"
        showIcon
        message="无法读取候选人资料"
        description={job.error?.message ?? batches.error?.message ?? '候选人不存在'}
      />
    )
  }

  const canWrite = canManageRecruitment(auth.user) && job.data.status !== 'archived'
  const canViewSensitive = canViewSensitiveRecruitmentData(auth.user)

  return (
    <>
      {contextHolder}
      <div className="page-heading">
        <div>
          <Title level={2}>{document.candidate_code}</Title>
          <Text type="secondary">
            {job.data.title} · {document.original_filename} · 结构化资料与分析版本
          </Text>
        </div>
        <Space wrap>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate(`/jobs/${jobId}/batches`)}
          >
            返回简历批次
          </Button>
          {canWrite && (
            <>
              <Button
                icon={<ReloadOutlined />}
                disabled={!latestProfile}
                onClick={() => setReanalysisOpen(true)}
              >
                单人重新分析
              </Button>
              <Button
                type="primary"
                icon={<EditOutlined />}
                disabled={!latestProfile}
                onClick={() => latestProfile && openEditor(latestProfile)}
              >
                修正结构化资料
              </Button>
            </>
          )}
        </Space>
      </div>

      {!canWrite && (
        <Alert
          type="warning"
          showIcon
          message="当前候选人资料仅供查看"
          description="当前角色不能修正档案或重新运行分析。"
          className="page-alert"
        />
      )}

      <Alert
        type="info"
        showIcon
        message="所有修正和重跑都会创建新版本"
        description="旧档案与旧分析结果不会被覆盖；失败重跑也不会替换当前已经完成的可用结果。"
        className="version-safety-alert"
      />

      <Tabs
        items={[
          {
            key: 'profiles',
            label: `资料版本（${profiles.data?.length ?? 0}）`,
            children: profiles.isPending ? (
              <Skeleton active paragraph={{ rows: 8 }} />
            ) : profiles.isError ? (
              <Alert type="error" showIcon message={profiles.error.message} />
            ) : !profiles.data?.length ? (
              <Empty description="尚无结构化候选人资料" />
            ) : (
              <Collapse
                defaultActiveKey={[profiles.data[0].id]}
                items={profiles.data.map((profile) => ({
                  key: profile.id,
                  label: (
                    <Space wrap>
                      <Text strong>档案 V{profile.version_number}</Text>
                      <Tag color={profile.source === 'manual' ? 'purple' : 'blue'}>
                        {profile.source === 'manual' ? '人工修正' : 'AI 提取'}
                      </Tag>
                      <Text type="secondary">{formatDate(profile.created_at)}</Text>
                    </Space>
                  ),
                  extra:
                    profile.id === latestProfile?.id && canWrite ? (
                      <Button
                        size="small"
                        icon={<EditOutlined />}
                        onClick={(event) => {
                          event.stopPropagation()
                          openEditor(profile)
                        }}
                      >
                        基于此版本修正
                      </Button>
                    ) : undefined,
                  children: (
                    <>
                      <Descriptions
                        size="small"
                        column={3}
                        items={[
                          { key: 'model', label: '来源模型', children: profile.model_name },
                          { key: 'prompt', label: 'Prompt', children: profile.prompt_version },
                          {
                            key: 'source',
                            label: '来源版本',
                            children: profile.source_profile_id ? '上一档案版本' : '初始提取',
                          },
                        ]}
                      />
                      <ProfileSnapshot profile={profile} showEvidence={canViewSensitive} />
                    </>
                  ),
                }))}
              />
            ),
          },
          {
            key: 'analysis',
            label: `分析历史（${history.data?.length ?? 0}）`,
            children: history.isPending ? (
              <Skeleton active paragraph={{ rows: 8 }} />
            ) : history.isError ? (
              <Alert type="error" showIcon message={history.error.message} />
            ) : !history.data?.length ? (
              <Empty description="尚无候选人分析历史" />
            ) : (
              <div className="analysis-history-list">
                {history.data.map((result) => (
                  <AnalysisHistoryCard key={result.id} result={result} />
                ))}
              </div>
            ),
          },
        ]}
      />

      {canWrite && <Modal
        title={editingProfile ? `修正结构化资料 · 基于档案 V${editingProfile.version_number}` : '修正结构化资料'}
        open={Boolean(editingProfile)}
        width={980}
        okText="保存新版本并重新分析"
        cancelText="取消"
        confirmLoading={correctionMutation.isPending}
        onOk={submitCorrection}
        onCancel={() => {
          setEditingProfile(undefined)
          setEditorValues(undefined)
        }}
      >
        <Alert
          type="warning"
          showIcon
          message="请只填写与招聘判断有关的结构化信息"
          description="不得补充姓名、电话、邮箱、证件号、地址或社交账号；证据中的片段编号和引用必须来自当前脱敏简历。"
          className="profile-editor-alert"
        />
        <label htmlFor="profile-correction-criteria">重新分析使用的职位标准</label>
        <Select
          id="profile-correction-criteria"
          className="profile-criteria-select"
          value={criteriaVersionId}
          onChange={setCriteriaVersionId}
          options={confirmedCriteria.map((item) => ({
            value: item.id,
            label: `标准 V${item.version_number} · 通过线 ${item.pass_threshold}`,
          }))}
        />
        <div className="profile-editor-grid">
          {editorValues &&
            profileSections.map(([key, label]) => (
              <div key={key} className="profile-editor-field">
                <label htmlFor={`profile-${key}`}>{label}（JSON 数组）</label>
                <Input.TextArea
                  id={`profile-${key}`}
                  value={editorValues[key]}
                  autoSize={{ minRows: 6, maxRows: 14 }}
                  onChange={(event) =>
                    setEditorValues((current) =>
                      current ? { ...current, [key]: event.target.value } : current,
                    )
                  }
                />
              </div>
            ))}
        </div>
      </Modal>}

      {canWrite && <Modal
        title="单人重新分析"
        open={reanalysisOpen}
        okText="确认重跑"
        cancelText="取消"
        confirmLoading={reanalysisMutation.isPending}
        okButtonProps={{ disabled: !criteriaVersionId }}
        onOk={() => reanalysisMutation.mutate()}
        onCancel={() => setReanalysisOpen(false)}
      >
        <Space direction="vertical" size="middle" className="full-width-space">
          <Alert
            type="info"
            showIcon
            message="将使用最新结构化档案创建新的分析版本"
            description="旧分析结果继续保留；本次失败不会影响旧结果。"
          />
          <div>
            <label htmlFor="candidate-reanalysis-criteria">职位标准版本</label>
            <Select
              id="candidate-reanalysis-criteria"
              className="profile-criteria-select"
              value={criteriaVersionId}
              onChange={setCriteriaVersionId}
              options={confirmedCriteria.map((item) => ({
                value: item.id,
                label: `标准 V${item.version_number} · 通过线 ${item.pass_threshold}`,
              }))}
            />
          </div>
          <Text type="secondary">
            当前档案：{latestProfile ? `V${latestProfile.version_number}` : '无可用档案'}
          </Text>
        </Space>
      </Modal>}
    </>
  )
}
