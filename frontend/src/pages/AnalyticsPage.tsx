import {
  InfoCircleOutlined,
  ReloadOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Empty,
  Input,
  Segmented,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import {
  fetchAnalyticsDashboard,
  type AnalyticsDashboardRecord,
  type AnalyticsQualityRecord,
  type AnalyticsRatioMetricRecord,
} from '../api/client'

const { Text, Title } = Typography
type RangePreset = '7' | '30' | '90' | 'custom'

const RANGE_OPTIONS = [
  { label: '近 7 天', value: '7' },
  { label: '近 30 天', value: '30' },
  { label: '近 90 天', value: '90' },
  { label: '自定义', value: 'custom' },
]

function localDateString(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function presetDates(days: number) {
  const end = new Date()
  const start = new Date(end)
  start.setDate(start.getDate() - days + 1)
  return { startDate: localDateString(start), endDate: localDateString(end) }
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function formatDuration(seconds: number | null) {
  if (seconds === null) return '暂无样本'
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`
  if (seconds < 86400) return `${(seconds / 3600).toFixed(seconds < 36000 ? 1 : 0)} 小时`
  return `${(seconds / 86400).toFixed(seconds < 864000 ? 1 : 0)} 天`
}

function RatioValue({ metric }: { metric: AnalyticsRatioMetricRecord }) {
  return (
    <div className="analytics-ratio-value">
      <strong>{metric.percentage === null ? '—' : `${metric.percentage}%`}</strong>
      <Text type="secondary">
        {metric.numerator} / {metric.denominator}
      </Text>
      {metric.denominator === 0 && <Tag>暂无口径</Tag>}
      {metric.small_sample && <Tag color="warning">小样本</Tag>}
    </div>
  )
}

function QualityNotice({ records }: { records: AnalyticsQualityRecord[] }) {
  const reasons = [...new Set(records.flatMap((record) => record.reasons))]
  const excluded = Math.max(...records.map((record) => record.excluded_count), 0)
  if (reasons.length === 0 && excluded === 0) return null
  return (
    <Alert
      type="warning"
      showIcon
      className="page-alert"
      message="部分历史数据未计入统计"
      description={`${reasons.join('；')}${excluded > 0 ? `。最多有 ${excluded} 条记录因数据不完整被排除` : ''}`}
    />
  )
}

function Overview({ data }: { data: AnalyticsDashboardRecord['overview'] }) {
  const metrics = [
    ['开放职位', data.active_job_count],
    ['新增应聘', data.application_count],
    ['去重候选人', data.unique_candidate_count],
    ['批准编制', data.approved_headcount],
    ['已入职', data.hired_count],
  ] as const
  return (
    <section className="analytics-overview" aria-label="招聘总览">
      {metrics.map(([label, value]) => (
        <div className="analytics-overview-metric" key={label}>
          <Text type="secondary">{label}</Text>
          <strong>{value}</strong>
        </div>
      ))}
      <div className="analytics-overview-metric analytics-overview-metric--accent">
        <Text type="secondary">招聘完成率</Text>
        <RatioValue metric={data.hiring_completion_rate} />
      </div>
    </section>
  )
}

function Trend({ data }: { data: AnalyticsDashboardRecord['trend'] }) {
  const maximum = Math.max(
    ...data.points.flatMap((point) => [
      point.applications_created,
      point.offers_accepted,
      point.onboardings_completed,
    ]),
    1,
  )
  return (
    <section className="analytics-section" aria-labelledby="analytics-trend-title">
      <div className="analytics-section-heading">
        <div>
          <Title level={3} id="analytics-trend-title">招聘趋势</Title>
          <Text type="secondary">按{data.interval === 'day' ? '日' : '周'}统计实际发生的业务事件</Text>
        </div>
        <div className="analytics-legend" aria-label="趋势图例">
          <span><i className="trend-key trend-key--application" />新增应聘</span>
          <span><i className="trend-key trend-key--offer" />接受 Offer</span>
          <span><i className="trend-key trend-key--onboarding" />已入职</span>
        </div>
      </div>
      {data.points.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前区间没有趋势数据" />
      ) : (
        <>
          <div className="analytics-trend-scroll">
            <div className="analytics-trend-chart" role="img" aria-label="新增应聘、接受 Offer 与已入职趋势">
              {data.points.map((point) => (
                <div className="analytics-trend-column" key={point.bucket_start}>
                  <div className="analytics-trend-bars">
                    {([
                      ['application', point.applications_created],
                      ['offer', point.offers_accepted],
                      ['onboarding', point.onboardings_completed],
                    ] as const).map(([kind, value]) => (
                      <Tooltip key={kind} title={`${value} 人`}>
                        <span
                          className={`analytics-trend-bar analytics-trend-bar--${kind}`}
                          style={{ height: `${Math.max(value === 0 ? 2 : 8, value / maximum * 100)}%` }}
                        />
                      </Tooltip>
                    ))}
                  </div>
                  <Text type="secondary">{point.bucket_start.slice(5)}</Text>
                </div>
              ))}
            </div>
          </div>
          <Table
            className="analytics-table analytics-trend-table"
            rowKey="bucket_start"
            size="small"
            pagination={data.points.length > 7 ? { pageSize: 7, showSizeChanger: false } : false}
            dataSource={data.points}
            scroll={{ x: 560 }}
            columns={[
              {
                title: '统计周期',
                key: 'bucket',
                render: (_, point) => point.bucket_start === point.bucket_end
                  ? point.bucket_start
                  : `${point.bucket_start} 至 ${point.bucket_end}`,
              },
              { title: '新增应聘', dataIndex: 'applications_created' },
              { title: '接受 Offer', dataIndex: 'offers_accepted' },
              { title: '已入职', dataIndex: 'onboardings_completed' },
            ]}
          />
        </>
      )}
    </section>
  )
}

function FunnelAndDistribution({ data }: { data: AnalyticsDashboardRecord }) {
  return (
    <div className="analytics-two-column">
      <section className="analytics-section" aria-labelledby="analytics-funnel-title">
        <div className="analytics-section-heading">
          <div>
            <Title level={3} id="analytics-funnel-title">历史转化漏斗</Title>
            <Text type="secondary">同一批新增应聘最终到达各节点的人数</Text>
          </div>
          <Tag>{data.funnel.cohort_size} 份应聘</Tag>
        </div>
        <div className="analytics-funnel">
          {data.funnel.stages.map((stage) => (
            <div className="analytics-funnel-row" key={stage.key}>
              <Text>{stage.label}</Text>
              <div className="analytics-funnel-track">
                <span style={{ width: `${stage.cohort_percentage ?? 0}%` }} />
              </div>
              <strong>{stage.count}</strong>
              <Text type="secondary">
                {stage.cohort_percentage === null ? '—' : `${stage.cohort_percentage}%`}
              </Text>
            </div>
          ))}
        </div>
      </section>

      <section className="analytics-section" aria-labelledby="analytics-current-title">
        <div className="analytics-section-heading">
          <div>
            <Title level={3} id="analytics-current-title">当前阶段分布</Title>
            <Text type="secondary">截至统计时间，每份有效应聘只计入一个阶段</Text>
          </div>
          <Tag>{data.current_distribution.total} 份有效应聘</Tag>
        </div>
        <div className="analytics-distribution">
          {data.current_distribution.stages.map((stage) => (
            <div key={stage.key}>
              <Text type="secondary">{stage.label}</Text>
              <strong>{stage.count}</strong>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

function StageDuration({ data }: { data: AnalyticsDashboardRecord['stage_duration'] }) {
  return (
    <section className="analytics-section" aria-labelledby="analytics-duration-title">
      <div className="analytics-section-heading">
        <div>
          <Title level={3} id="analytics-duration-title">阶段耗时</Title>
          <Text type="secondary">仅统计已离开该阶段的样本，当前仍停留的应聘单独列出</Text>
        </div>
      </div>
      <Table
        className="analytics-table"
        rowKey="stage"
        pagination={false}
        scroll={{ x: 680 }}
        dataSource={data.stages}
        locale={{ emptyText: '当前区间暂无阶段耗时样本' }}
        columns={[
          { title: '阶段', dataIndex: 'label', width: 180 },
          { title: 'P50', dataIndex: 'p50_seconds', render: formatDuration },
          { title: 'P90', dataIndex: 'p90_seconds', render: formatDuration },
          { title: '完成样本', dataIndex: 'sample_size' },
          { title: '仍在阶段', dataIndex: 'current_open_count' },
          {
            title: '排除',
            dataIndex: 'excluded_count',
            render: (value: number) => value > 0 ? <Tag color="warning">{value}</Tag> : 0,
          },
        ]}
      />
    </section>
  )
}

function QualityMetrics({ data }: { data: AnalyticsDashboardRecord }) {
  const decisionTotal = data.decision_difference.ai_screened_count
  return (
    <section className="analytics-section" aria-labelledby="analytics-quality-title">
      <div className="analytics-section-heading">
        <div>
          <Title level={3} id="analytics-quality-title">转化与决策质量</Title>
          <Text type="secondary">比例均展示真实分子与分母，低于 5 个分母时标记小样本</Text>
        </div>
      </div>
      <div className="analytics-ratio-grid">
        {[data.interviews.round_pass_rate, data.interviews.candidate_pass_rate, data.offers.acceptance_rate, data.onboardings.completion_rate].map((metric) => (
          <div className="analytics-ratio" key={metric.key}>
            <Text>{metric.label}</Text>
            <RatioValue metric={metric} />
          </div>
        ))}
      </div>
      <div className="analytics-decision-heading">
        <Title level={4}>AI 与人工决策差异</Title>
        <Text type="secondary">基于 {decisionTotal} 份已完成 AI 筛选的应聘</Text>
      </div>
      <div className="analytics-decision-grid">
        {data.decision_difference.categories.map((category) => (
          <div key={category.key}>
            <Text type="secondary">{category.label}</Text>
            <strong>{category.count}</strong>
            <Text>{category.percentage === null ? '—' : `${category.percentage}%`}</Text>
          </div>
        ))}
      </div>
      <div className="analytics-state-grid">
        <div>
          <Title level={4}>Offer 状态</Title>
          <ul>
            {data.offers.statuses.map((status) => (
              <li key={status.key}><Text type="secondary">{status.label}</Text><strong>{status.count}</strong></li>
            ))}
          </ul>
        </div>
        <div>
          <Title level={4}>入职状态</Title>
          <ul>
            {data.onboardings.statuses.map((status) => (
              <li key={status.key}><Text type="secondary">{status.label}</Text><strong>{status.count}</strong></li>
            ))}
          </ul>
        </div>
        <div>
          <Title level={4}>放弃入职来源</Title>
          {data.onboardings.abandonment_sources.length === 0 ? (
            <Text type="secondary">当前区间没有放弃入职记录</Text>
          ) : (
            <ul>
              {data.onboardings.abandonment_sources.map((source) => (
                <li key={source.key}><Text type="secondary">{source.label}</Text><strong>{source.count}</strong></li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  )
}

export function AnalyticsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const rawRange = searchParams.get('range')
  const range: RangePreset = ['7', '30', '90', 'custom'].includes(rawRange ?? '')
    ? (rawRange as RangePreset)
    : '30'
  const defaults = presetDates(range === 'custom' ? 30 : Number(range))
  const startDate = range === 'custom' ? searchParams.get('start') ?? defaults.startDate : defaults.startDate
  const endDate = range === 'custom' ? searchParams.get('end') ?? defaults.endDate : defaults.endDate
  const jobId = searchParams.get('job') || undefined
  const validRange = startDate <= endDate

  const dashboard = useQuery({
    queryKey: ['analytics', 'dashboard', { startDate, endDate, jobId }],
    queryFn: () => fetchAnalyticsDashboard({ startDate, endDate, jobId }),
    enabled: validRange,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
  })

  const qualityRecords = useMemo(() => {
    if (!dashboard.data) return []
    return [
      dashboard.data.overview.quality,
      dashboard.data.funnel.quality,
      dashboard.data.current_distribution.quality,
      dashboard.data.trend.quality,
      dashboard.data.stage_duration.quality,
      dashboard.data.interviews.quality,
      dashboard.data.offers.quality,
      dashboard.data.onboardings.quality,
      dashboard.data.decision_difference.quality,
    ]
  }, [dashboard.data])

  function updateParams(updates: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams)
    Object.entries(updates).forEach(([key, value]) => {
      if (value) next.set(key, value)
      else next.delete(key)
    })
    setSearchParams(next, { replace: true })
  }

  function selectRange(nextRange: RangePreset) {
    if (nextRange === 'custom') {
      updateParams({ range: nextRange, start: startDate, end: endDate })
      return
    }
    updateParams({ range: nextRange, start: undefined, end: undefined })
  }

  return (
    <>
      <div className="page-heading analytics-heading">
        <div>
          <Title level={2}>招聘数据分析</Title>
          <Text type="secondary">从业务记录实时聚合招聘进度、转化效率与决策差异</Text>
        </div>
        <Space wrap>
          {dashboard.data && <Text type="secondary">统计于 {formatDateTime(dashboard.data.meta.as_of)}</Text>}
          <Tooltip title="刷新分析数据">
            <Button
              aria-label="刷新分析数据"
              icon={<ReloadOutlined />}
              loading={dashboard.isFetching}
              onClick={() => void dashboard.refetch()}
            />
          </Tooltip>
        </Space>
      </div>

      <section className="analytics-filters" aria-label="分析筛选">
        <Segmented
          aria-label="统计时间范围"
          value={range}
          options={RANGE_OPTIONS}
          onChange={(value) => selectRange(value as RangePreset)}
        />
        {range === 'custom' && (
          <div className="analytics-date-range">
            <Input
              aria-label="统计开始日期"
              type="date"
              value={startDate}
              onChange={(event) => updateParams({ start: event.target.value })}
            />
            <Text type="secondary">至</Text>
            <Input
              aria-label="统计结束日期"
              type="date"
              value={endDate}
              onChange={(event) => updateParams({ end: event.target.value })}
            />
          </div>
        )}
        <Select
          aria-label="按岗位筛选分析"
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="全部可见岗位"
          value={jobId}
          loading={dashboard.isPending}
          options={(dashboard.data?.jobs ?? []).map((job) => ({
            value: job.id,
            label: `${job.title}${job.status === 'archived' ? '（已归档）' : ''}`,
          }))}
          onChange={(value) => updateParams({ job: value })}
        />
      </section>

      {!validRange && (
        <Alert type="error" showIcon className="page-alert" message="开始日期不能晚于结束日期" />
      )}
      {dashboard.isError && (
        <Alert
          type="error"
          showIcon
          className="page-alert"
          message="招聘分析读取失败"
          description={dashboard.error.message}
          action={<Button onClick={() => void dashboard.refetch()}>重试</Button>}
        />
      )}
      {dashboard.isPending && validRange && (
        <div className="analytics-loading"><Skeleton active paragraph={{ rows: 12 }} /></div>
      )}
      {dashboard.data && (
        <div className="analytics-page">
          <QualityNotice records={qualityRecords} />
          <div className="analytics-snapshot-note">
            <InfoCircleOutlined />
            <Text type="secondary">
              统计区间 {dashboard.data.meta.query.start_date} 至 {dashboard.data.meta.query.end_date}，时区为上海；当前可见 {dashboard.data.meta.visible_job_count} 个岗位。
            </Text>
          </div>
          <Overview data={dashboard.data.overview} />
          <Trend data={dashboard.data.trend} />
          <FunnelAndDistribution data={dashboard.data} />
          <StageDuration data={dashboard.data.stage_duration} />
          <QualityMetrics data={dashboard.data} />
          {dashboard.data.overview.quality.excluded_count > 0 && (
            <div className="analytics-footnote"><WarningOutlined /> 数据不完整记录不会被推断为成功或失败。</div>
          )}
        </div>
      )}
    </>
  )
}
