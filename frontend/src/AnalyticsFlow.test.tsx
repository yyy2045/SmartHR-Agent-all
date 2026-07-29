import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

const jobId = '11111111-1111-4111-8111-111111111111'
const meta = {
  as_of: '2026-07-29T08:00:00Z',
  timezone: 'Asia/Shanghai',
  query: { start_date: '2026-07-01', end_date: '2026-07-29', job_id: null },
  visible_job_count: 1,
}
const quality = { complete: true, excluded_count: 0, reasons: [] }
const ratio = (
  key: string,
  label: string,
  numerator: number,
  denominator: number,
  percentage: number | null,
  small_sample = false,
) => ({ key, label, numerator, denominator, percentage, small_sample })

const dashboard = {
  meta,
  jobs: [{ id: jobId, title: '后端工程师', status: 'active' }],
  overview: {
    meta,
    quality,
    active_job_count: 1,
    selected_job_count: 1,
    application_count: 10,
    unique_candidate_count: 9,
    approved_headcount: 2,
    hired_count: 1,
    linked_hired_count: 1,
    hiring_completion_rate: ratio('hiring_completion_rate', '招聘完成率', 1, 2, 50, true),
  },
  funnel: {
    meta,
    quality,
    cohort_size: 10,
    stages: [
      ['application_created', '新增应聘', 10, 100],
      ['ai_screening_completed', 'AI 筛选完成', 9, 90],
      ['recruiter_shortlisted', '人工通过', 7, 70],
      ['interview_started', '进入面试', 5, 50],
      ['interview_passed', '面试通过', 3, 30],
      ['offer_approved', 'Offer 批准', 2, 20],
      ['offer_accepted', 'Offer 接受', 1, 10],
      ['onboarding_completed', '已入职', 1, 10],
    ].map(([key, label, count, cohort_percentage]) => ({
      key,
      label,
      count,
      cohort_percentage,
    })),
  },
  current_distribution: {
    meta,
    quality,
    total: 10,
    stages: [
      ['unprocessed', '未处理', 1],
      ['pending', '待定', 1],
      ['shortlisted', '已通过', 1],
      ['to_contact', '待联系', 1],
      ['contacted', '已联系', 1],
      ['to_interview', '待面试', 1],
      ['completed', '面试完成', 1],
      ['rejected', '已淘汰', 1],
      ['offer_pending_response', 'Offer 待回应', 1],
      ['offer_rejected', 'Offer 已拒绝', 0],
      ['onboarding_pending_confirmation', '入职待确认', 0],
      ['onboarding_pending_start', '待入职', 0],
      ['onboarding_completed', '已入职', 1],
      ['onboarding_abandoned', '放弃入职', 0],
    ].map(([key, label, count]) => ({ key, label, count })),
  },
  trend: {
    meta,
    quality,
    interval: 'day',
    points: [
      {
        bucket_start: '2026-07-28',
        bucket_end: '2026-07-28',
        applications_created: 4,
        offers_accepted: 1,
        onboardings_completed: 0,
      },
      {
        bucket_start: '2026-07-29',
        bucket_end: '2026-07-29',
        applications_created: 6,
        offers_accepted: 0,
        onboardings_completed: 1,
      },
    ],
  },
  stage_duration: {
    meta,
    quality,
    stages: [
      {
        stage: 'application_created',
        label: '应聘至 AI 完成',
        sample_size: 9,
        p50_seconds: 120,
        p90_seconds: 600,
        excluded_count: 0,
        current_open_count: 1,
      },
    ],
  },
  interviews: {
    meta,
    quality,
    round_pass_rate: ratio('interview_round_pass_rate', '面试轮次通过率', 3, 5, 60),
    candidate_pass_rate: ratio('interview_candidate_pass_rate', '候选人面试通过率', 2, 3, 66.7, true),
  },
  offers: {
    meta,
    quality,
    total_offers: 2,
    statuses: [
      ['draft', '草稿', 0],
      ['pending_manager_confirmation', '待用人经理确认', 0],
      ['pending_approval', '待审批', 0],
      ['approved', '已批准', 0],
      ['rejected', '已驳回', 0],
      ['pending_response', '待候选人回应', 1],
      ['accepted', '已接受', 1],
      ['declined', '已拒绝', 0],
    ].map(([key, label, count]) => ({ key, label, count })),
    acceptance_rate: ratio('offer_acceptance_rate', 'Offer 接受率', 1, 2, 50, true),
  },
  onboardings: {
    meta,
    quality,
    total_records: 1,
    statuses: [
      ['pending_confirmation', '待确认', 0],
      ['candidate_proposed_date', '候选人提议日期', 0],
      ['pending_start', '待入职', 0],
      ['onboarded', '已入职', 1],
      ['abandoned', '放弃入职', 0],
    ].map(([key, label, count]) => ({ key, label, count })),
    completion_rate: ratio('onboarding_completion_rate', '入职完成率', 1, 1, 100, true),
    abandonment_sources: [],
  },
  decision_difference: {
    meta,
    quality,
    ai_screened_count: 9,
    categories: [
      ['consistent', '一致', 5, 55.6],
      ['human_upgraded', '人工上调', 1, 11.1],
      ['human_downgraded', '人工下调', 1, 11.1],
      ['missing_human_decision', '缺人工决定', 2, 22.2],
    ].map(([key, label, count, percentage]) => ({ key, label, count, percentage })),
  },
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderApp(path = '/analytics?range=custom&start=2026-07-01&end=2026-07-29') {
  window.history.replaceState({}, '', path)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

describe('招聘数据分析流程', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    window.history.replaceState({}, '', '/')
  })

  it('允许审批人查看同快照指标并把岗位筛选保存在 URL', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(input.toString(), 'http://localhost')
      if (url.pathname === '/api/auth/me') {
        return json({
          id: 'approver-1',
          username: 'approver',
          display_name: '审批负责人',
          is_active: true,
          must_change_password: false,
          roles: ['approver'],
        })
      }
      if (url.pathname === '/api/health/live') return json({ status: 'ok' })
      if (url.pathname === '/api/analytics/dashboard') return json(dashboard)
      return json({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderApp()

    expect(await screen.findByRole('heading', { name: '招聘数据分析' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '数据分析' })).toHaveAttribute('aria-current', 'page')
    expect(await screen.findByRole('heading', { name: '历史转化漏斗' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '当前阶段分布' })).toBeInTheDocument()
    expect(screen.getAllByText('小样本').length).toBeGreaterThan(0)
    expect(screen.getAllByText('50%').length).toBeGreaterThan(0)

    fireEvent.mouseDown(screen.getByRole('combobox', { name: '按岗位筛选分析' }))
    fireEvent.click(await screen.findByText('后端工程师'))
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('job')).toBe(jobId))

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map(([input]) => input.toString())
      expect(calls).toContain(
        `/api/analytics/dashboard?start_date=2026-07-01&end_date=2026-07-29&job_id=${jobId}`,
      )
    })
  })

  it('显示零分母和接口错误，不用虚构百分比', async () => {
    let dashboardCalls = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(input.toString(), 'http://localhost')
        if (url.pathname === '/api/auth/me') {
          return json({
            id: 'admin-1', username: 'admin', display_name: '管理员', is_active: true,
            must_change_password: false, roles: ['administrator'],
          })
        }
        if (url.pathname === '/api/health/live') return json({ status: 'ok' })
        if (url.pathname === '/api/jobs') return json([])
        if (url.pathname === '/api/analytics/dashboard') {
          dashboardCalls += 1
          if (dashboardCalls === 1) return json({ detail: '分析服务暂不可用' }, 503)
          return json({
            ...dashboard,
            overview: {
              ...dashboard.overview,
              hiring_completion_rate: ratio('hiring_completion_rate', '招聘完成率', 0, 0, null),
            },
          })
        }
        return json({ detail: 'not found' }, 404)
      }),
    )

    renderApp()

    expect(await screen.findByText('招聘分析读取失败')).toBeInTheDocument()
    expect(screen.getByText('分析服务暂不可用')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(await screen.findByText('暂无口径')).toBeInTheDocument()
    expect(screen.getByText('0 / 0')).toBeInTheDocument()
  })
})
