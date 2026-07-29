import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

const user = {
  id: 'approver-1',
  username: 'approver',
  display_name: '审批负责人',
  is_active: true,
  must_change_password: false,
  roles: ['approver'],
}

const jobId = '11111111-1111-4111-8111-111111111111'

const summary = {
  as_of: '2026-07-29T08:00:00Z',
  total_count: 3,
  action_required_count: 1,
  sections: [
    { section: 'action_required', count: 1 },
    { section: 'waiting_external', count: 1 },
    { section: 'risk_failure', count: 1 },
  ],
  priorities: [
    { priority: 'urgent', count: 1 },
    { priority: 'high', count: 1 },
    { priority: 'normal', count: 1 },
  ],
  types: [
    { item_type: 'recruitment_request_approval', count: 1 },
    { item_type: 'offer_link', count: 1 },
    { item_type: 'system_failure', count: 1 },
  ],
  jobs: [{ id: jobId, title: '后端工程师' }],
  partial: false,
  failed_sources: [],
}

const actionItem = {
  stable_key: 'recruitment_request_approval:request-1',
  section: 'action_required',
  item_type: 'recruitment_request_approval',
  source: 'recruitment_requests',
  priority: 'high',
  title: '审批招聘需求：后端工程师',
  summary: '计划招聘 2 人',
  count: 1,
  occurred_at: '2026-07-29T07:00:00Z',
  risk_at: '2026-08-01T15:59:59Z',
  job_id: null,
  job_title: null,
  target_path: '/recruitment-requests?selected=request-1',
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderApp(path = '/workbench?priority=high') {
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

describe('招聘工作台流程', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    sessionStorage.clear()
    window.history.replaceState({}, '', '/')
  })

  it('展示三个平级区域，并从待办安全返回原筛选状态', async () => {
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 240 })
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0)
      return 1
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(input.toString(), 'http://localhost')
      if (url.pathname === '/api/auth/me') return json(user)
      if (url.pathname === '/api/health/live') return json({ status: 'ok' })
      if (url.pathname === '/api/workbench/summary') return json(summary)
      if (url.pathname === '/api/workbench/items') {
        const section = url.searchParams.get('section')
        return json({
          as_of: summary.as_of,
          items: section === 'action_required' ? [actionItem] : [],
          total: section === 'action_required' ? 1 : 0,
          page: 1,
          page_size: 6,
          partial: false,
          failed_sources: [],
        })
      }
      if (url.pathname === '/api/recruitment-requests') return json([])
      return json({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderApp()

    expect(await screen.findByRole('heading', { name: '招聘工作台' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '需要我处理' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '等待外部回应' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '风险与失败' })).toBeInTheDocument()
    expect(await screen.findByText('审批招聘需求：后端工程师')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '工作台' })).toHaveAttribute(
      'aria-current',
      'page',
    )

    fireEvent.click(screen.getByRole('button', { name: /去处理/ }))
    await waitFor(() => expect(window.location.pathname).toBe('/recruitment-requests'))
    expect(new URLSearchParams(window.location.search).get('selected')).toBe('request-1')
    expect(new URLSearchParams(window.location.search).get('returnTo')).toBe(
      '/workbench?priority=high',
    )
    expect(sessionStorage.getItem('smarthr:workbench-scroll')).toBe('240')

    fireEvent.click(await screen.findByRole('button', { name: '返回工作台' }))
    await waitFor(() => expect(window.location.pathname).toBe('/workbench'))
    expect(window.location.search).toBe('?priority=high')
    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith({ top: 240, behavior: 'instant' }))
  })

  it('保留成功数据并明确提示部分失败来源', async () => {
    const partialSummary = {
      ...summary,
      total_count: 0,
      action_required_count: 0,
      sections: [
        { section: 'action_required', count: 0 },
        { section: 'waiting_external', count: 0 },
        { section: 'risk_failure', count: 0 },
      ],
      priorities: [
        { priority: 'urgent', count: 0 },
        { priority: 'high', count: 0 },
        { priority: 'normal', count: 0 },
      ],
      types: [],
      jobs: [],
      partial: true,
      failed_sources: ['offers'],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(input.toString(), 'http://localhost')
        if (url.pathname === '/api/auth/me') return json(user)
        if (url.pathname === '/api/health/live') return json({ status: 'ok' })
        if (url.pathname === '/api/workbench/summary') return json(partialSummary)
        if (url.pathname === '/api/workbench/items') {
          return json({
            as_of: summary.as_of,
            items: [],
            total: 0,
            page: 1,
            page_size: 6,
            partial: true,
            failed_sources: ['offers'],
          })
        }
        return json({ detail: 'not found' }, 404)
      }),
    )

    renderApp('/workbench')

    expect(await screen.findByText('部分数据暂不可用')).toBeInTheDocument()
    expect(screen.getByText(/未能读取：Offer/)).toBeInTheDocument()
    expect(screen.getAllByText('当前筛选条件下没有事项')).toHaveLength(3)
  })

  it('把类型、优先级、岗位和分区页码保存在 URL 中', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(input.toString(), 'http://localhost')
      if (url.pathname === '/api/auth/me') return json(user)
      if (url.pathname === '/api/health/live') return json({ status: 'ok' })
      if (url.pathname === '/api/workbench/summary') return json(summary)
      if (url.pathname === '/api/workbench/items') {
        const section = url.searchParams.get('section')
        const page = Number(url.searchParams.get('page') ?? 1)
        const items =
          section === 'action_required'
            ? Array.from({ length: page === 1 ? 6 : 1 }, (_, index) => ({
                ...actionItem,
                stable_key: `approval:${page}:${index}`,
                title: `审批招聘需求 ${page}-${index + 1}`,
              }))
            : []
        return json({
          as_of: summary.as_of,
          items,
          total: section === 'action_required' ? 7 : 0,
          page,
          page_size: 6,
          partial: false,
          failed_sources: [],
        })
      }
      return json({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/workbench')

    await screen.findByText('审批招聘需求 1-1')
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '按事项类型筛选' }))
    fireEvent.click(await screen.findByText('招聘需求审批（1）'))
    await waitFor(() =>
      expect(new URLSearchParams(window.location.search).get('type')).toBe(
        'recruitment_request_approval',
      ),
    )

    fireEvent.mouseDown(screen.getByRole('combobox', { name: '按优先级筛选' }))
    fireEvent.click(await screen.findByText('高'))
    await waitFor(() =>
      expect(new URLSearchParams(window.location.search).get('priority')).toBe('high'),
    )

    fireEvent.mouseDown(screen.getByRole('combobox', { name: '按岗位筛选' }))
    fireEvent.click(await screen.findByText('后端工程师'))
    await waitFor(() =>
      expect(new URLSearchParams(window.location.search).get('job')).toBe(jobId),
    )

    fireEvent.click(await screen.findByTitle('2'))
    await waitFor(() =>
      expect(new URLSearchParams(window.location.search).get('actionPage')).toBe('2'),
    )
    expect(await screen.findByText('审批招聘需求 2-1')).toBeInTheDocument()

    const workbenchCalls = fetchMock.mock.calls
      .map(([input]) => input.toString())
      .filter((path) => path.startsWith('/api/workbench/items?'))
    expect(workbenchCalls).toContain(
      `/api/workbench/items?section=action_required&item_type=recruitment_request_approval&priority=high&job_id=${jobId}&page=2&page_size=6`,
    )

    fireEvent.click(screen.getByRole('button', { name: '清除筛选' }))
    await waitFor(() => expect(window.location.search).toBe(''))
  })
})
