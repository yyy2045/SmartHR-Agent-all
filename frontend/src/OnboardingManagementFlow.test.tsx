import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type {
  AuthUser,
  OnboardingDetailRecord,
  OnboardingSummaryRecord,
} from './api/client'

const timestamp = '2026-07-29T08:00:00Z'
const job = {
  id: 'job-1',
  recruiter_id: 'recruiter-1',
  hiring_manager_id: 'manager-1',
  recruitment_request_id: null,
  title: '高级后端工程师',
  department: '研发中心',
  original_jd: '负责核心服务开发',
  status: 'active',
  archived_at: null,
  created_at: timestamp,
  updated_at: timestamp,
}

const users: Record<string, AuthUser> = {
  recruiter: {
    id: 'recruiter-1',
    username: 'recruiter',
    display_name: '招聘专员',
    is_active: true,
    must_change_password: false,
    roles: ['recruiter'],
  },
  manager: {
    id: 'manager-1',
    username: 'manager',
    display_name: '用人经理',
    is_active: true,
    must_change_password: false,
    roles: ['hiring_manager'],
  },
  administrator: {
    id: 'admin-1',
    username: 'administrator',
    display_name: '企业管理员',
    is_active: true,
    must_change_password: false,
    roles: ['administrator'],
  },
}

function summary(overrides: Partial<OnboardingSummaryRecord> = {}): OnboardingSummaryRecord {
  return {
    id: 'onboarding-1',
    application_id: 'application-1',
    offer_id: 'offer-1',
    job_id: job.id,
    job_title: job.title,
    job_status: 'active',
    recruiter_available: true,
    candidate_id: 'candidate-1',
    candidate_code: 'CAND-0001',
    candidate_name: '候选人A',
    candidate_phone: '13800001234',
    status: 'candidate_proposed_date',
    version: 2,
    action_owner: 'recruiter',
    start_date_overdue: false,
    expected_start_date: '2026-09-01',
    candidate_proposed_date: '2026-09-08',
    recruiter_proposed_date: null,
    confirmed_start_date: null,
    actual_start_date: null,
    abandonment_source: null,
    abandonment_reason_code: null,
    updated_at: timestamp,
    ...overrides,
  }
}

function detail(overrides: Partial<OnboardingDetailRecord> = {}): OnboardingDetailRecord {
  return {
    ...summary(),
    abandonment_note: null,
    events: [
      {
        id: 'event-1',
        sequence_number: 1,
        action: 'created',
        from_status: null,
        to_status: 'pending_confirmation',
        date_before: null,
        date_after: null,
        reason: '候选人接受 Offer，系统创建入职记录',
        actor_type: 'system',
        actor_username: null,
        actor_display_name: null,
        created_at: timestamp,
      },
      {
        id: 'event-2',
        sequence_number: 2,
        action: 'candidate_proposed_date',
        from_status: 'pending_confirmation',
        to_status: 'candidate_proposed_date',
        date_before: null,
        date_after: '2026-09-08',
        reason: '完成工作交接',
        actor_type: 'candidate',
        actor_username: null,
        actor_display_name: null,
        created_at: '2026-07-29T09:00:00Z',
      },
    ],
    ...overrides,
  }
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderApp(path = '/onboardings') {
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

function commonResponse(path: string, user: AuthUser, item: OnboardingSummaryRecord) {
  if (path === '/api/auth/me') return jsonResponse(user)
  if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
  if (path === '/api/jobs?include_archived=true') return jsonResponse([job])
  if (path === '/api/onboardings?page=1&page_size=100') {
    return jsonResponse({ items: [item], total: 1, page: 1, page_size: 100 })
  }
  return undefined
}

async function openDetail() {
  fireEvent.click(await screen.findByText('候选人A'))
  expect(await screen.findByText('状态记录')).toBeInTheDocument()
}

async function findModalByTitle(title: string) {
  const matches = await screen.findAllByText(title)
  const dialog = matches
    .map((match) => match.closest('.ant-modal[role="dialog"]'))
    .find((candidate): candidate is HTMLElement => candidate instanceof HTMLElement)
  if (!dialog) throw new Error(`未找到标题为“${title}”的弹窗`)
  return dialog
}

describe('onboarding management flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('招聘专员确认候选人提出的日期并提交最新资源版本', async () => {
    let currentSummary = summary()
    let currentDetail = detail()
    let requestPayload: Record<string, unknown> | undefined
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const common = commonResponse(path, users.recruiter, currentSummary)
      if (common) return common
      if (path === '/api/onboardings/onboarding-1') return jsonResponse(currentDetail)
      if (path === '/api/offers/offer-1/portal-links') return jsonResponse([])
      if (path === '/api/onboardings/onboarding-1/date-decision' && init?.method === 'POST') {
        requestPayload = JSON.parse(init.body as string) as Record<string, unknown>
        currentSummary = summary({
          status: 'pending_start',
          version: 3,
          action_owner: 'none',
          confirmed_start_date: '2026-09-08',
        })
        currentDetail = detail({
          ...currentSummary,
          events: currentDetail.events,
        })
        return jsonResponse(currentDetail)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    expect(await screen.findByRole('heading', { name: '入职跟踪' })).toBeInTheDocument()
    expect(await screen.findByText('13800001234')).toBeInTheDocument()
    await openDetail()
    fireEvent.click(screen.getByRole('button', { name: /接受候选人日期/ }))
    const dialog = await findModalByTitle('确认候选人提出的入职日期？')
    fireEvent.click(within(dialog).getByRole('button', { name: /确认日期/ }))

    expect(await screen.findByText('已确认候选人入职日期')).toBeInTheDocument()
    expect(requestPayload).toMatchObject({
      version: 2,
      decision: 'accept',
      proposed_date: null,
    })
    expect((await screen.findAllByText('待入职')).length).toBeGreaterThan(0)
  })

  it('用人经理只能查看负责职位摘要且不能看到电话和状态操作', async () => {
    const managerSummary = summary({ candidate_phone: null })
    const managerDetail = detail({ candidate_phone: null })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const common = commonResponse(path, users.manager, managerSummary)
      if (common) return common
      if (path === '/api/onboardings/onboarding-1') return jsonResponse(managerDetail)
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    expect(await screen.findByText('联系方式受限')).toBeInTheDocument()
    await openDetail()
    expect(screen.getByText('无权限查看')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '接受候选人日期' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '标记放弃' })).not.toBeInTheDocument()
    expect(
      fetchMock.mock.calls.some(([input]) => input.toString().includes('/portal-links')),
    ).toBe(false)
  })

  it('管理员通过追加事件更正误标的已入职状态', async () => {
    const onboardedSummary = summary({
      status: 'onboarded',
      version: 4,
      action_owner: 'none',
      confirmed_start_date: '2026-09-08',
      actual_start_date: '2026-09-08',
    })
    let onboardedDetail = detail({ ...onboardedSummary })
    let correctionPayload: Record<string, unknown> | undefined
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const common = commonResponse(path, users.administrator, onboardedSummary)
      if (common) return common
      if (path === '/api/onboardings/onboarding-1') return jsonResponse(onboardedDetail)
      if (path === '/api/offers/offer-1/portal-links') return jsonResponse([])
      if (path === '/api/onboardings/onboarding-1/corrections' && init?.method === 'POST') {
        correctionPayload = JSON.parse(init.body as string) as Record<string, unknown>
        onboardedDetail = detail({
          ...onboardedSummary,
          status: 'pending_start',
          version: 5,
          actual_start_date: null,
        })
        return jsonResponse(onboardedDetail)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp()

    await openDetail()
    fireEvent.click(screen.getByRole('button', { name: /更正误标/ }))
    const dialog = await findModalByTitle('更正误标的已入职状态')
    fireEvent.change(within(dialog).getByRole('textbox', { name: '更正原因' }), {
      target: { value: '招聘专员误点已入职' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: /确\s*认/ }))

    await waitFor(() => expect(correctionPayload).toMatchObject({
      version: 4,
      reason: '招聘专员误点已入职',
    }))
    expect(await screen.findByText('已追加状态更正')).toBeInTheDocument()
  })

  it('通过安全深链自动打开详情并返回原 Offer', async () => {
    const currentSummary = summary({ status: 'pending_start', action_owner: 'none' })
    const currentDetail = detail({ ...currentSummary })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const common = commonResponse(path, users.recruiter, currentSummary)
      if (common) return common
      if (path === '/api/onboardings/onboarding-1') return jsonResponse(currentDetail)
      if (path === '/api/offers/offer-1/portal-links') return jsonResponse([])
      if (path === '/api/offers') return jsonResponse([])
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/onboardings?selected=onboarding-1&from=%2Foffers%3Fselected%3Doffer-1')

    expect(await screen.findByText('状态记录')).toBeInTheDocument()
    const backButton = screen.getByRole('button', { name: /返回 Offer 详情/ })
    fireEvent.click(backButton)

    await waitFor(() => {
      expect(window.location.pathname).toBe('/offers')
      expect(new URLSearchParams(window.location.search).get('selected')).toBe('offer-1')
    })
  })

  it('拒绝外部来源地址且关闭详情时保留安全来源参数', async () => {
    const currentSummary = summary()
    const currentDetail = detail()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const common = commonResponse(path, users.recruiter, currentSummary)
      if (common) return common
      if (path === '/api/onboardings/onboarding-1') return jsonResponse(currentDetail)
      if (path === '/api/offers/offer-1/portal-links') return jsonResponse([])
      return jsonResponse({ detail: 'not found' }, 404)
    }))
    renderApp('/onboardings?selected=onboarding-1&from=https%3A%2F%2Fevil.example%2Foffers')

    expect(await screen.findByText('状态记录')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /返回来源页面/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))

    await waitFor(() => {
      const query = new URLSearchParams(window.location.search)
      expect(query.get('selected')).toBeNull()
      expect(query.get('from')).toBe('https://evil.example/offers')
    })
  })

  it('提示归档职位、失效负责人和过期历史日期并允许补录入职', async () => {
    const currentSummary = summary({
      status: 'pending_confirmation',
      action_owner: 'candidate',
      expected_start_date: '2020-01-01',
      job_status: 'archived',
      recruiter_available: false,
      start_date_overdue: true,
    })
    const currentDetail = detail({ ...currentSummary })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const common = commonResponse(path, users.administrator, currentSummary)
      if (common) return common
      if (path === '/api/onboardings/onboarding-1') return jsonResponse(currentDetail)
      if (path === '/api/offers/offer-1/portal-links') return jsonResponse([])
      return jsonResponse({ detail: 'not found' }, 404)
    }))
    renderApp()
    await openDetail()

    expect(screen.getByText('职位当前没有可用招聘专员')).toBeInTheDocument()
    expect(screen.getByText('职位已归档')).toBeInTheDocument()
    expect(screen.getByText('计划入职日期已过')).toBeInTheDocument()
    expect(screen.getByText(/只有管理员可以继续处理/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /标记已入职/ })).toBeInTheDocument()
  })
})
