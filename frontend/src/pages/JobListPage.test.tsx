import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { RoleKey } from '../api/client'
import { AuthContext, type AuthContextValue } from '../auth/context'
import { JobListPage } from './JobListPage'

const recruiterId = 'user-recruiter'
const hiringManagerId = 'user-manager'

const jobs = [
  {
    id: 'job-1',
    recruiter_id: recruiterId,
    hiring_manager_id: hiringManagerId,
    title: '后端工程师',
    department: '技术平台部',
    original_jd: '负责平台研发与服务治理',
    status: 'active',
    archived_at: null,
    created_at: '2026-07-26T08:00:00Z',
    updated_at: '2026-07-26T08:00:00Z',
  },
  {
    id: 'job-2',
    recruiter_id: recruiterId,
    hiring_manager_id: hiringManagerId,
    title: '产品经理',
    department: '企业产品部',
    original_jd: '负责招聘产品规划',
    status: 'active',
    archived_at: null,
    created_at: '2026-07-26T09:00:00Z',
    updated_at: '2026-07-26T09:00:00Z',
  },
]

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="current-path">{location.pathname}</div>
}

function authValue(id: string, roles: RoleKey[]): AuthContextValue {
  return {
    user: {
      id,
      username: id,
      display_name: id,
      is_active: true,
      must_change_password: false,
      roles,
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
}

function renderPage(
  path: string,
  auth: AuthContextValue = authValue(recruiterId, ['recruiter']),
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={auth}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route
              path="/jobs/:jobId"
              element={
                <>
                  <JobListPage />
                  <LocationProbe />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

describe('岗位管理卡片', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('只保留岗位自身操作，并可在列表中切换当前岗位', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(jobs), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    renderPage('/jobs/job-1')

    expect(await screen.findByRole('heading', { name: '岗位管理' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '后端工程师' })).toBeInTheDocument()
    expect(screen.getByText('当前岗位')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /编辑职位/ })).toHaveLength(2)
    expect(screen.queryByRole('button', { name: '面试方案' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '流程看板' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '筛选结果' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '简历批次' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '配置筛选标准' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '设为当前岗位' }))

    await waitFor(() =>
      expect(screen.getByTestId('current-path')).toHaveTextContent('/jobs/job-2'),
    )
    expect(screen.getByText('当前岗位')).toBeInTheDocument()
  })

  it('用人经理只能查看负责岗位，不能创建、编辑或归档', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(jobs), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    renderPage('/jobs/job-1', authValue(hiringManagerId, ['hiring_manager']))

    expect(await screen.findByRole('heading', { name: '岗位管理' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '新建职位' })).not.toBeInTheDocument()
    expect(await screen.findAllByRole('button', { name: /查看职位/ })).toHaveLength(2)
    expect(screen.queryByRole('button', { name: /更多操作/ })).not.toBeInTheDocument()
  })
})
