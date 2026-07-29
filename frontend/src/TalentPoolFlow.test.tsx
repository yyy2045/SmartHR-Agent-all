import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { AuthUser, TalentPoolGroupRecord, TalentPoolMembershipRecord } from './api/client'

const timestamp = '2026-07-29T08:00:00Z'
const group: TalentPoolGroupRecord = {
  id: '11111111-1111-4111-8111-111111111111',
  name: '后端人才',
  description: '适合平台研发岗位',
  version: 2,
  is_archived: false,
  member_count: 1,
  created_by_id: '22222222-2222-4222-8222-222222222222',
  created_by_display_name: '招聘专员',
  archived_at: null,
  archived_by_id: null,
  archived_by_display_name: null,
  created_at: timestamp,
  updated_at: timestamp,
}
const membership: TalentPoolMembershipRecord = {
  id: '33333333-3333-4333-8333-333333333333',
  group_id: group.id,
  group_name: group.name,
  group_archived: false,
  candidate_id: '44444444-4444-4444-8444-444444444444',
  candidate_code: 'CAND-000000000001',
  candidate_name: '张三',
  phone: '13800138000',
  email: 'zhangsan@example.com',
  status: 'active',
  reason: '具备大型平台经验',
  source_application_id: null,
  version: 1,
  joined_at: timestamp,
  removed_at: null,
  updated_at: timestamp,
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function user(roles: AuthUser['roles']): AuthUser {
  return {
    id: '22222222-2222-4222-8222-222222222222',
    username: roles[0],
    display_name: '测试用户',
    is_active: true,
    must_change_password: false,
    roles,
  }
}

function renderTalentPool(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  window.history.replaceState({}, '', '/talent')
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

function apiFor(
  authUser: AuthUser,
  onRequest?: (path: string, init?: RequestInit) => Response | undefined,
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = input.toString()
    if (path === '/api/auth/me') return jsonResponse(authUser)
    if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
    if (path === '/api/jobs?include_archived=true') return jsonResponse([])
    const custom = onRequest?.(path, init)
    if (custom) return custom
    if (path.startsWith('/api/talent-pool/groups?')) {
      return jsonResponse({ items: [group], total: 1, limit: 100, offset: 0 })
    }
    if (path.startsWith('/api/talent-pool/memberships?')) {
      const item = authUser.roles.includes('hiring_manager')
        ? { ...membership, phone: null, email: null }
        : membership
      return jsonResponse({ items: [item], total: 1, limit: 20, offset: 0 })
    }
    return jsonResponse({ detail: 'not found' }, 404)
  })
}

describe('talent pool', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('招聘专员查看人才并创建版本化分组', async () => {
    let createPayload: Record<string, unknown> | undefined
    const fetchMock = apiFor(user(['recruiter']), (path, init) => {
      if (path === '/api/talent-pool/groups' && init?.method === 'POST') {
        createPayload = JSON.parse(init.body as string) as Record<string, unknown>
        return jsonResponse({ ...group, id: '55555555-5555-4555-8555-555555555555', name: '架构师' })
      }
      return undefined
    })
    renderTalentPool(fetchMock)

    expect(await screen.findByRole('heading', { name: '企业人才库' })).toBeInTheDocument()
    expect(await screen.findByText('张三')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '分组' }))
    fireEvent.click(await screen.findByRole('button', { name: /新建分组/ }))
    fireEvent.change(screen.getByRole('textbox', { name: '分组名称' }), {
      target: { value: '架构师' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: '分组说明' }), {
      target: { value: '长期关注的架构候选人' },
    })
    const saveButton = screen
      .getByRole('dialog')
      .querySelector<HTMLButtonElement>('.ant-modal-footer .ant-btn-primary')
    expect(saveButton).not.toBeNull()
    fireEvent.click(saveButton!)

    expect(await screen.findByText('人才分组已创建')).toBeInTheDocument()
    expect(createPayload).toMatchObject({
      name: '架构师',
      description: '长期关注的架构候选人',
    })
    expect(createPayload?.idempotency_key).toEqual(expect.any(String))
  })

  it('用人经理只读查看人才且联系方式隐藏', async () => {
    renderTalentPool(apiFor(user(['hiring_manager'])))

    expect(await screen.findByRole('heading', { name: '企业人才库' })).toBeInTheDocument()
    expect(await screen.findByText('张三')).toBeInTheDocument()
    expect(screen.queryByText('13800138000')).not.toBeInTheDocument()
    expect(screen.queryByText('zhangsan@example.com')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /移出/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '分组' }))
    expect(screen.queryByRole('button', { name: /新建分组/ })).not.toBeInTheDocument()
  })

  it('审批人没有人才库导航且路由返回无权访问', async () => {
    renderTalentPool(apiFor(user(['approver'])))

    expect(await screen.findByText('无权访问')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '人才库' })).not.toBeInTheDocument()
  })
})
