import {
  FileTextOutlined,
  ReloadOutlined,
  RightOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Empty,
  Input,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  ApiError,
  fetchCandidateProcesses,
  fetchInterviewReports,
  fetchJob,
  type CandidateProcessCardRecord,
  type InterviewReportConclusion,
  type InterviewReportSummary,
} from '../api/client'
import { InterviewModuleNav } from '../components/InterviewModuleNav'

const { Title, Text } = Typography

type ReportFilter = 'all' | 'missing' | 'draft' | 'confirmed'

interface ReportListRow {
  application?: CandidateProcessCardRecord
  report?: InterviewReportSummary
}

const aiGroupMeta = {
  passed: { label: '通过组', color: 'success' },
  low_match: { label: '低匹配组', color: 'warning' },
  auto_rejected: { label: '自动淘汰组', color: 'error' },
} as const

const evaluationMeta = {
  not_started: { label: '待评价', color: 'default' },
  in_progress: { label: '评价进行中', color: 'processing' },
  completed: { label: '评价完成', color: 'success' },
  cancelled: { label: '轮次已取消', color: 'default' },
} as const

const conclusionLabels: Record<InterviewReportConclusion, string> = {
  hire: '录用',
  next_round: '下一轮',
  reserve: '保留',
  reject: '淘汰',
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function latestApplicationCards(
  candidates: CandidateProcessCardRecord[],
): CandidateProcessCardRecord[] {
  const latest = new Map<string, CandidateProcessCardRecord>()
  for (const candidate of candidates) {
    const current = latest.get(candidate.application_id)
    if (
      !current ||
      new Date(candidate.analysis_created_at).getTime() >
        new Date(current.analysis_created_at).getTime()
    ) {
      latest.set(candidate.application_id, candidate)
    }
  }
  return [...latest.values()]
}

export function InterviewReportListPage() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [reportFilter, setReportFilter] = useState<ReportFilter>('all')
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
  const reports = useQuery({
    queryKey: ['interview-reports', jobId],
    queryFn: () => fetchInterviewReports(jobId!),
    enabled: Boolean(jobId),
  })

  const reportRows = useMemo(() => {
    const reportByApplication = new Map(
      (reports.data ?? []).map((report) => [report.application_id, report]),
    )
    const applicationRows = latestApplicationCards(candidates.data ?? [])
      .map<ReportListRow>((application) => ({
        application,
        report: reportByApplication.get(application.application_id),
      }))
    const applicationIds = new Set(
      applicationRows.map((row) => row.application?.application_id),
    )
    const reportOnlyRows = (reports.data ?? [])
      .filter((report) => !applicationIds.has(report.application_id))
      .map<ReportListRow>((report) => ({ report }))
    return [...applicationRows, ...reportOnlyRows]
      .sort((left, right) => {
        const leftDate = left.report?.updated_at ?? left.application?.analysis_created_at ?? ''
        const rightDate = right.report?.updated_at ?? right.application?.analysis_created_at ?? ''
        return new Date(rightDate).getTime() - new Date(leftDate).getTime()
      })
  }, [candidates.data, reports.data])

  const rows = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return reportRows
      .filter(({ application, report }) => {
        if (reportFilter !== 'all') {
          if (reportFilter === 'missing' && report) return false
          if (reportFilter !== 'missing' && report?.status !== reportFilter) return false
        }
        if (!normalizedQuery) return true
        return [
          application?.candidate_code ?? report?.candidate_code ?? '',
          application?.original_filename ?? '',
          report?.candidate_name ?? '',
        ].filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(normalizedQuery)
      })
  }, [query, reportFilter, reportRows])

  const reportCounts = useMemo(() => ({
    total: reportRows.length,
    draft: reportRows.filter((row) => row.report?.status === 'draft').length,
    confirmed: reportRows.filter((row) => row.report?.status === 'confirmed').length,
  }), [reportRows])
  const pageError = job.error ?? candidates.error ?? reports.error
  const loading = job.isPending || candidates.isPending || reports.isPending

  function openReport(applicationId: string) {
    navigate(
      `/jobs/${encodeURIComponent(jobId!)}/applications/${encodeURIComponent(applicationId)}/interview-report`,
    )
  }

  const columns: TableColumnsType<ReportListRow> = [
    {
      title: '候选人',
      key: 'candidate',
      render: (_, row) => (
        <div className="report-candidate-cell">
          <Text strong>{row.report?.candidate_name || row.application?.candidate_code}</Text>
          <Text type="secondary">
            {row.report?.candidate_name
              ? row.application?.candidate_code ?? row.report.candidate_code
              : row.application?.original_filename ?? row.report?.candidate_code}
          </Text>
        </div>
      ),
    },
    {
      title: '智能筛选',
      key: 'screening',
      width: 170,
      responsive: ['sm'],
      render: (_, row) => row.application ? (
          <Space size="small" wrap>
            <Text strong>{row.application.total_score.toFixed(1)} 分</Text>
            <Tag color={aiGroupMeta[row.application.ai_group].color}>
              {aiGroupMeta[row.application.ai_group].label}
            </Tag>
          </Space>
        ) : <Text type="secondary">无筛选摘要</Text>,
    },
    {
      title: '面试评价',
      key: 'evaluation',
      width: 200,
      responsive: ['md'],
      render: (_, row) => {
        const progress = row.application?.interview_evaluation
        if (!progress) return <Text type="secondary">未安排面试</Text>
        return (
          <div className="report-evaluation-cell">
            <Tag color={evaluationMeta[progress.status].color}>
              {evaluationMeta[progress.status].label}
            </Tag>
            <Text type="secondary">
              {progress.submitted_count}/{progress.total_rounds} 轮已提交
            </Text>
          </div>
        )
      },
    },
    {
      title: '报告状态',
      key: 'report',
      width: 190,
      render: (_, row) => {
        if (!row.report) return <Tag>未创建</Tag>
        return (
          <Space size="small" wrap>
            <Tag color={row.report.status === 'confirmed' ? 'success' : 'processing'}>
              {row.report.status === 'confirmed' ? '已确认' : '草稿'} · V
              {row.report.current_version_number}
            </Tag>
            {row.report.current_conclusion && (
              <Text type="secondary">
                {conclusionLabels[row.report.current_conclusion]}
              </Text>
            )}
          </Space>
        )
      },
    },
    {
      title: '最近更新',
      key: 'updated',
      width: 130,
      responsive: ['lg'],
      render: (_, row) => (
        <Text type="secondary">
          {formatDate(row.report?.updated_at ?? row.application?.analysis_created_at ?? '')}
        </Text>
      ),
    },
    {
      title: '',
      key: 'action',
      width: 130,
      align: 'right',
      fixed: 'right',
      render: (_, row) => (
        <Button
          type={row.report ? 'default' : 'primary'}
          icon={row.report ? <FileTextOutlined /> : <RightOutlined />}
          onClick={() => openReport(row.application?.application_id ?? row.report!.application_id)}
        >
          {row.report ? '查看报告' : '开始报告'}
        </Button>
      ),
    },
  ]

  return (
    <>
      <div className="page-heading">
        <div>
          <Space size="small" wrap>
            <Title level={2}>{job.data?.title ?? '面试报告'}</Title>
            {job.data?.status === 'archived' && <Tag>已归档</Tag>}
          </Space>
          <Text type="secondary">集中处理候选人的面试结论与历史版本</Text>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={candidates.isFetching || reports.isFetching}
          onClick={() => {
            void candidates.refetch()
            void reports.refetch()
          }}
        >
          刷新
        </Button>
      </div>

      <InterviewModuleNav jobId={jobId} activeKey="reports" />

      {pageError && (
        <Alert
          className="page-alert"
          type="error"
          showIcon
          message="无法读取面试报告列表"
          description={pageError instanceof ApiError ? pageError.message : '请稍后重试'}
        />
      )}
      {loading && <Skeleton active paragraph={{ rows: 10 }} />}

      {!loading && !pageError && (
        <>
          <section className="report-summary-strip" aria-label="面试报告概览">
            <div><Text type="secondary">候选人</Text><strong>{reportCounts.total}</strong></div>
            <div><Text type="secondary">待创建</Text><strong>{reportCounts.total - reportCounts.draft - reportCounts.confirmed}</strong></div>
            <div><Text type="secondary">草稿</Text><strong>{reportCounts.draft}</strong></div>
            <div><Text type="secondary">已确认</Text><strong>{reportCounts.confirmed}</strong></div>
          </section>

          <div className="report-list-toolbar">
            <Input
              allowClear
              prefix={<SearchOutlined />}
              value={query}
              placeholder="搜索候选人或简历文件"
              onChange={(event) => setQuery(event.target.value)}
            />
            <Select<ReportFilter>
              value={reportFilter}
              options={[
                { value: 'all', label: '全部报告状态' },
                { value: 'missing', label: '未创建' },
                { value: 'draft', label: '草稿' },
                { value: 'confirmed', label: '已确认' },
              ]}
              onChange={setReportFilter}
            />
          </div>

          {rows.length === 0 ? (
            <section className="empty-workspace">
              <Empty description="当前条件下没有候选人" />
            </section>
          ) : (
            <Table<ReportListRow>
              className="report-list-table"
              rowKey={(row) => row.application?.application_id ?? row.report!.application_id}
              columns={columns}
              dataSource={rows}
              pagination={{ pageSize: 20, showSizeChanger: false }}
              scroll={{ x: 760 }}
            />
          )}
        </>
      )}
    </>
  )
}
