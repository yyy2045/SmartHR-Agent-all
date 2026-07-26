import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/context'
import { AppLayout } from './AppLayout'
import { businessModuleForPath, defaultPathForModule, jobIdFromPath } from './navigation'

const auth: AuthContextValue = {
  user: { id: 'user-1', username: 'recruiter', display_name: '招聘专员' },
  isLoading: false,
  isLoggingIn: false,
  isLoggingOut: false,
  error: null,
  login: vi.fn(),
  logout: vi.fn(),
  retry: vi.fn(),
}

function renderLayout(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={auth}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="*" element={<><Outlet /><LocationProbe /></>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="current-path">{location.pathname}</div>
}

const jobs = [
  {
    id: 'job-1',
    title: '后端工程师',
    department: '技术平台部',
    original_jd: '负责平台研发',
    status: 'active' as const,
    archived_at: null,
    created_at: '2026-07-26T08:00:00Z',
    updated_at: '2026-07-26T08:00:00Z',
  },
  {
    id: 'job-2',
    title: '产品经理',
    department: '企业产品部',
    original_jd: '负责招聘产品',
    status: 'archived' as const,
    archived_at: '2026-07-26T09:00:00Z',
    created_at: '2026-07-26T08:00:00Z',
    updated_at: '2026-07-26T09:00:00Z',
  },
]

describe('招聘业务导航', () => {
  afterEach(() => vi.unstubAllGlobals())

  function mockApi() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = input.toString()
        let body: unknown = { status: 'ok' }
        if (path === '/api/jobs?include_archived=true') body = jobs
        if (path === '/api/jobs/job-1') body = { ...jobs[0], criteria_versions: [] }
        if (path === '/api/jobs/job-2') body = { ...jobs[1], criteria_versions: [] }
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )
  }

  it.each([
    ['/jobs/job-1/batches', 'screening', '智能筛选'],
    ['/jobs/job-1/results', 'screening', '智能筛选'],
    ['/jobs/job-1/pipeline', 'candidate-process', '候选人流程'],
    [
      '/jobs/job-1/batches/batch-1/documents/document-1/history',
      'candidate-process',
      '候选人流程',
    ],
    ['/jobs/job-1/interview-plan', 'interviews', '面试管理'],
    [
      '/jobs/job-1/candidates/document-1/interview-schedule',
      'interviews',
      '面试管理',
    ],
    [
      '/jobs/job-1/candidates/document-1/interview-evaluations/round-1',
      'interviews',
      '面试管理',
    ],
    ['/jobs/job-1/criteria', 'jobs', '岗位管理'],
  ])('将 %s 归入 %s 模块', (path, module, label) => {
    expect(businessModuleForPath(path)).toBe(module)
    expect(jobIdFromPath(path)).toBe('job-1')
    mockApi()
    renderLayout(path)
    expect(screen.getByRole('button', { name: label })).toHaveAttribute('aria-current', 'page')
  })

  it('无岗位上下文时展示完整导航，并禁用岗位级模块', () => {
    mockApi()
    renderLayout('/')

    expect(screen.getByRole('button', { name: /岗位管理/ })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.getByRole('button', { name: /智能筛选/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /候选人流程/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /面试管理/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /人才库/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /数据分析/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /系统设置/ })).toBeDisabled()
  })

  it('新建岗位页没有错误的岗位上下文', () => {
    expect(jobIdFromPath('/jobs/new')).toBeNull()
  })

  it('按当前业务模块生成岗位切换后的安全默认页', () => {
    expect(defaultPathForModule('jobs', 'job-2')).toBe('/jobs/job-2/edit')
    expect(defaultPathForModule('screening', 'job-2')).toBe('/jobs/job-2/batches')
    expect(defaultPathForModule('candidate-process', 'job-2')).toBe('/jobs/job-2/pipeline')
    expect(defaultPathForModule('interviews', 'job-2')).toBe('/jobs/job-2/interview-plan')
  })

  it('展示当前岗位信息，并在切换岗位后保持候选人流程模块', async () => {
    mockApi()
    renderLayout('/jobs/job-1/pipeline')

    expect(await screen.findByText('技术平台部')).toBeInTheDocument()
    expect(screen.getByText('招聘中')).toBeInTheDocument()

    fireEvent.mouseDown(screen.getByRole('combobox', { name: '切换当前岗位' }))
    fireEvent.click(await screen.findByText('产品经理（已归档）'))

    await waitFor(() =>
      expect(screen.getByTestId('current-path')).toHaveTextContent('/jobs/job-2/pipeline'),
    )
    expect(screen.getByRole('button', { name: '候选人流程' })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })
})
