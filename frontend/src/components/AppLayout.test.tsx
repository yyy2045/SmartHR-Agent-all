import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/context'
import { AppLayout } from './AppLayout'
import { businessModuleForPath, jobIdFromPath } from './navigation'

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
              <Route path="*" element={<><Outlet /><div>页面内容</div></>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

describe('招聘业务导航', () => {
  afterEach(() => vi.unstubAllGlobals())

  function mockHealth() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
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
    ['/jobs/job-1/criteria', 'jobs', '岗位管理'],
  ])('将 %s 归入 %s 模块', (path, module, label) => {
    expect(businessModuleForPath(path)).toBe(module)
    expect(jobIdFromPath(path)).toBe('job-1')
    mockHealth()
    renderLayout(path)
    expect(screen.getByRole('button', { name: label })).toHaveAttribute('aria-current', 'page')
  })

  it('无岗位上下文时展示完整导航，并禁用岗位级模块', () => {
    mockHealth()
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
})
