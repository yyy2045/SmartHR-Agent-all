import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/context'
import { AppLayout } from './AppLayout'
import { businessModuleForPath, jobIdFromPath } from './navigation'

const auth: AuthContextValue = {
  user: {
    id: 'user-1',
    username: 'recruiter',
    display_name: '招聘专员',
    is_active: true,
    must_change_password: false,
    roles: ['recruiter'],
  },
  isLoading: false,
  isLoggingIn: false,
  isLoggingOut: false,
  isChangingPassword: false,
  error: null,
  login: vi.fn(),
  logout: vi.fn(),
  changePassword: vi.fn(),
  retry: vi.fn(),
}

function renderLayout(path: string, authValue: AuthContextValue = auth) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={authValue}>
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

describe('招聘业务导航', () => {
  afterEach(() => vi.unstubAllGlobals())

  function mockApi() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = input.toString()
        let body: unknown = { status: 'ok' }
        if (path === '/api/notifications/unread-count') body = { unread_count: 1 }
        if (path.startsWith('/api/notifications?')) {
          body = {
            items: [
              {
                id: 'notification-1',
                notification_type: 'offer_approved',
                title: 'Offer 审批通过',
                summary: '请继续处理候选人的 Offer。',
                resource_type: 'offer',
                resource_id: 'offer-1',
                route_path: '/offers',
                read_at: null,
                created_at: '2026-08-05T10:00:00Z',
              },
            ],
            total: 1,
            unread_count: 1,
            limit: 8,
            offset: 0,
          }
        }
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
    ['/jobs/job-1/interview-reports', 'interviews', '面试管理'],
    [
      '/jobs/job-1/applications/application-1/interview-report',
      'interviews',
      '面试管理',
    ],
    [
      '/jobs/job-1/applications/application-1/interview-schedule',
      'interviews',
      '面试管理',
    ],
    [
      '/jobs/job-1/applications/application-1/interview-evaluations/round-1',
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

  it('将录用管理归入全局模块且不显示岗位上下文', () => {
    expect(businessModuleForPath('/offers')).toBe('hiring')
    expect(businessModuleForPath('/onboardings')).toBe('hiring')
    expect(jobIdFromPath('/offers')).toBeNull()
    mockApi()
    renderLayout('/offers')
    expect(screen.getByRole('button', { name: '录用管理' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.queryByRole('combobox', { name: '切换当前岗位' })).not.toBeInTheDocument()
  })

  it('将全局候选人中心归入独立模块且不显示岗位上下文', () => {
    expect(businessModuleForPath('/candidates')).toBe('candidates')
    expect(jobIdFromPath('/candidates')).toBeNull()
    mockApi()
    renderLayout('/candidates')
    expect(screen.getByRole('button', { name: '候选人中心' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.queryByRole('combobox', { name: '切换当前岗位' })).not.toBeInTheDocument()
  })

  it('将人才库归入全局模块并允许用人经理只读进入', () => {
    expect(businessModuleForPath('/talent')).toBe('talent')
    expect(jobIdFromPath('/talent')).toBeNull()
    mockApi()
    renderLayout('/talent', {
      ...auth,
      user: { ...auth.user!, roles: ['hiring_manager'] },
    })
    expect(screen.getByRole('button', { name: '人才库' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '人才库' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.queryByRole('combobox', { name: '切换当前岗位' })).not.toBeInTheDocument()
  })

  it('将数据分析归入四角色可访问的全局模块', () => {
    expect(businessModuleForPath('/analytics')).toBe('analytics')
    expect(jobIdFromPath('/analytics')).toBeNull()
    mockApi()
    renderLayout('/analytics')
    expect(screen.getByRole('button', { name: '数据分析' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '数据分析' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.queryByRole('combobox', { name: '切换当前岗位' })).not.toBeInTheDocument()
  })

  it('无岗位上下文时展示完整导航，并禁用岗位级模块', () => {
    mockApi()
    renderLayout('/jobs')

    expect(screen.getByRole('button', { name: /岗位管理/ })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.getByRole('button', { name: /智能筛选/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /候选人流程/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /候选人中心/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /面试管理/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /录用管理/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /工作台/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /AI 控制台/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /人才库/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /数据分析/ })).toBeEnabled()
    expect(screen.queryByRole('button', { name: /系统设置/ })).not.toBeInTheDocument()
  })

  it('将 AI 控制台归入全局模块且不显示岗位上下文', () => {
    expect(businessModuleForPath('/ai-console')).toBe('ai-console')
    expect(jobIdFromPath('/ai-console')).toBeNull()
    mockApi()
    renderLayout('/ai-console')
    expect(screen.getByRole('button', { name: 'AI 控制台' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.queryByRole('combobox', { name: '切换当前岗位' })).not.toBeInTheDocument()
    expect(screen.getByText('管理可观测、可追溯、可评测的 AI Agent 工程能力')).toBeInTheDocument()
  })

  it('将工作台归入独立全局模块且不绑定岗位', () => {
    expect(businessModuleForPath('/workbench')).toBe('workbench')
    expect(jobIdFromPath('/workbench')).toBeNull()
    mockApi()
    renderLayout('/workbench')
    expect(screen.getByRole('button', { name: '工作台' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.queryByRole('combobox', { name: '切换当前岗位' })).not.toBeInTheDocument()
  })

  it('只接受指向工作台的站内返回地址', async () => {
    mockApi()
    const safe = renderLayout('/offers?returnTo=%2Fworkbench%3Fpriority%3Dhigh')
    fireEvent.click(screen.getByRole('button', { name: '返回工作台' }))
    await waitFor(() =>
      expect(screen.getByTestId('current-path')).toHaveTextContent('/workbench'),
    )
    safe.unmount()

    renderLayout('/offers?returnTo=https%3A%2F%2Fevil.example%2Fworkbench')
    expect(screen.queryByRole('button', { name: '返回工作台' })).not.toBeInTheDocument()
  })

  it('新建岗位页没有错误的岗位上下文', () => {
    expect(jobIdFromPath('/jobs/new')).toBeNull()
  })

  it('将岗位依赖功能作为岗位管理的连续二级菜单展示', () => {
    mockApi()
    renderLayout('/jobs/job-1/batches')

    const labels = within(screen.getByRole('navigation', { name: '主导航' }))
      .getAllByRole('button')
      .map((item) => item.getAttribute('aria-label'))
    const jobIndex = labels.indexOf('岗位管理')

    expect(labels.slice(jobIndex, jobIndex + 4)).toEqual([
      '岗位管理',
      '智能筛选',
      '候选人流程',
      '面试管理',
    ])
    expect(screen.queryByRole('combobox', { name: '切换当前岗位' })).not.toBeInTheDocument()
  })

  it('点击消息中心在当前页面打开通知抽屉', async () => {
    mockApi()
    renderLayout('/workbench')

    fireEvent.click(screen.getByRole('button', { name: '消息中心' }))

    expect(screen.getByRole('dialog', { name: '消息通知' })).toBeInTheDocument()
    expect(await screen.findByText('Offer 审批通过')).toBeInTheDocument()
    expect(screen.getByTestId('current-path')).toHaveTextContent('/workbench')
  })
})
