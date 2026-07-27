import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { AuthUser, JobInput, ManagedUser } from './api/client'

const timestamp = '2026-07-28T08:00:00Z'
const administrator: AuthUser = {
  id: 'admin-1',
  username: 'admin',
  display_name: '企业管理员',
  is_active: true,
  must_change_password: false,
  roles: ['administrator'],
}
const recruiter: AuthUser = {
  id: 'recruiter-1',
  username: 'recruiter',
  display_name: '招聘专员',
  is_active: true,
  must_change_password: false,
  roles: ['recruiter'],
}
const hiringManager: AuthUser = {
  id: 'manager-1',
  username: 'manager',
  display_name: '用人经理',
  is_active: true,
  must_change_password: false,
  roles: ['hiring_manager'],
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderApp(path: string) {
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

describe('用户、角色与岗位界面权限', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('管理员可进入用户管理并创建临时密码账号', async () => {
    let users: ManagedUser[] = [
      {
        ...administrator,
        created_at: timestamp,
        updated_at: timestamp,
      },
    ]
    let createdPayload: unknown = null
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = input.toString()
        const method = init?.method ?? 'GET'
        if (path === '/api/auth/me') return jsonResponse(administrator)
        if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
        if (path === '/api/jobs?include_archived=true') return jsonResponse([])
        if (path === '/api/users' && method === 'GET') return jsonResponse(users)
        if (path === '/api/users' && method === 'POST') {
          createdPayload = JSON.parse(init?.body as string)
          const created: ManagedUser = {
            id: 'recruiter-2',
            username: 'recruiter.two',
            display_name: '招聘专员二号',
            is_active: true,
            must_change_password: true,
            roles: ['recruiter'],
            created_at: timestamp,
            updated_at: timestamp,
          }
          users = [...users, created]
          return jsonResponse(created, 201)
        }
        return jsonResponse({ detail: 'not found' }, 404)
      }),
    )

    renderApp('/settings/users')

    expect(await screen.findByRole('heading', { name: '用户与权限' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '系统设置' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    fireEvent.click(screen.getByRole('button', { name: /创建用户/ }))
    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'recruiter.two' },
    })
    fireEvent.change(screen.getByLabelText('姓名'), {
      target: { value: '招聘专员二号' },
    })
    fireEvent.change(screen.getByLabelText('临时密码'), {
      target: { value: 'temporary-123' },
    })
    fireEvent.click(screen.getByLabelText('招聘专员'))
    fireEvent.click(
      within(screen.getByRole('dialog', { name: '创建用户' })).getByRole('button', {
        name: /创\s*建/,
      }),
    )

    expect(await screen.findByText('招聘专员二号')).toBeInTheDocument()
    expect(createdPayload).toEqual({
      username: 'recruiter.two',
      display_name: '招聘专员二号',
      temporary_password: 'temporary-123',
      roles: ['recruiter'],
    })
  })

  it('非管理员直接访问用户管理时显示 403', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = input.toString()
        if (path === '/api/auth/me') return jsonResponse(recruiter)
        if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
        if (path === '/api/jobs?include_archived=true') return jsonResponse([])
        return jsonResponse({ detail: 'not found' }, 404)
      }),
    )

    renderApp('/settings/users')

    expect(await screen.findByText('无权访问')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '用户与权限' })).not.toBeInTheDocument()
  })

  it('管理员创建职位时必须选择招聘专员并可指定用人经理', async () => {
    let createdPayload: JobInput | null = null
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = input.toString()
        const method = init?.method ?? 'GET'
        if (path === '/api/auth/me') return jsonResponse(administrator)
        if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
        if (path === '/api/jobs?include_archived=true') return jsonResponse([])
        if (path === '/api/users/options?role=recruiter') {
          return jsonResponse([{ ...recruiter, roles: ['recruiter'] }])
        }
        if (path === '/api/users/options?role=hiring_manager') {
          return jsonResponse([{ ...hiringManager, roles: ['hiring_manager'] }])
        }
        if (path === '/api/jobs' && method === 'POST') {
          createdPayload = JSON.parse(init?.body as string) as JobInput
          return jsonResponse(
            {
              id: 'job-1',
              ...createdPayload,
              recruiter_id: recruiter.id,
              hiring_manager_id: hiringManager.id,
              status: 'active',
              archived_at: null,
              created_at: timestamp,
              updated_at: timestamp,
            },
            201,
          )
        }
        if (path === '/api/jobs' && method === 'GET') return jsonResponse([])
        return jsonResponse({ detail: 'not found' }, 404)
      }),
    )

    renderApp('/jobs/new')

    expect(await screen.findByRole('heading', { name: '新建职位' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('职位名称'), { target: { value: '平台工程师' } })
    fireEvent.change(screen.getByLabelText('所属部门'), { target: { value: '研发中心' } })
    fireEvent.change(screen.getByLabelText('原始 JD'), { target: { value: '负责平台建设。' } })

    fireEvent.mouseDown(screen.getByLabelText('招聘专员'))
    fireEvent.click(await screen.findByText('招聘专员（recruiter）'))
    fireEvent.mouseDown(screen.getByLabelText('用人经理'))
    fireEvent.click(await screen.findByText('用人经理（manager）'))
    fireEvent.click(screen.getByRole('button', { name: /创建并配置标准/ }))

    await waitFor(() =>
      expect(createdPayload).toEqual({
        title: '平台工程师',
        department: '研发中心',
        original_jd: '负责平台建设。',
        recruiter_id: recruiter.id,
        hiring_manager_id: hiringManager.id,
      }),
    )
  })

  it('招聘专员只能选择用人经理，用人经理打开职位表单时完全只读', async () => {
    const job = {
      id: 'job-1',
      recruiter_id: recruiter.id,
      hiring_manager_id: hiringManager.id,
      title: '平台工程师',
      department: '研发中心',
      original_jd: '负责平台建设。',
      status: 'active',
      archived_at: null,
      created_at: timestamp,
      updated_at: timestamp,
      criteria_versions: [],
    }
    let currentUser = recruiter
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = input.toString()
        if (path === '/api/auth/me') return jsonResponse(currentUser)
        if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
        if (path === '/api/jobs?include_archived=true') return jsonResponse([job])
        if (path === '/api/jobs/job-1') return jsonResponse(job)
        if (path === '/api/users/options?role=hiring_manager') {
          return jsonResponse([{ ...hiringManager, roles: ['hiring_manager'] }])
        }
        return jsonResponse({ detail: 'not found' }, 404)
      }),
    )

    const recruiterView = renderApp('/jobs/new')
    expect(await screen.findByLabelText('用人经理')).toBeInTheDocument()
    expect(screen.queryByLabelText('招聘专员')).not.toBeInTheDocument()
    recruiterView.unmount()

    currentUser = hiringManager
    renderApp('/jobs/job-1/edit')
    expect(await screen.findByRole('heading', { name: '查看职位' })).toBeInTheDocument()
    expect(screen.getByLabelText('职位名称')).toBeDisabled()
    expect(screen.getByLabelText('所属部门')).toBeDisabled()
    expect(screen.getByLabelText('原始 JD')).toBeDisabled()
    expect(screen.queryByRole('button', { name: /保存修改/ })).not.toBeInTheDocument()
  })
})
