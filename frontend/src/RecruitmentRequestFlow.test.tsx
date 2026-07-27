import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type {
  AuthUser,
  RecruitmentRequestRecord,
  RecruitmentRequestVersion,
} from './api/client'
import { AuthContext, type AuthContextValue } from './auth/context'
import { RecruitmentRequestPage } from './pages/RecruitmentRequestPage'

const manager: AuthUser = {
  id: 'manager-1',
  username: 'manager',
  display_name: '用人经理',
  is_active: true,
  must_change_password: false,
  roles: ['hiring_manager'],
}

const recruiter: AuthUser = {
  id: 'recruiter-1',
  username: 'recruiter',
  display_name: '招聘专员',
  is_active: true,
  must_change_password: false,
  roles: ['recruiter'],
}

const approver: AuthUser = {
  id: 'approver-1',
  username: 'approver',
  display_name: '审批人',
  is_active: true,
  must_change_password: false,
  roles: ['approver'],
}

const authBase: Omit<AuthContextValue, 'user'> = {
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

function version(overrides: Partial<RecruitmentRequestVersion> = {}): RecruitmentRequestVersion {
  return {
    id: 'version-1',
    version_number: 1,
    source_version_id: null,
    created_by_id: manager.id,
    created_by_username: manager.username,
    created_by_display_name: manager.display_name,
    job_title: '高级后端工程师',
    headcount: 2,
    reason: '核心平台扩容',
    priority: 'high',
    target_start_date: '2026-09-15',
    salary_min: 25000,
    salary_max: 35000,
    notes: '优先高并发经验',
    created_at: '2026-07-28T08:00:00Z',
    ...overrides,
  }
}

function requestRecord(
  overrides: Partial<RecruitmentRequestRecord> = {},
): RecruitmentRequestRecord {
  const currentVersion = overrides.current_version ?? version()
  return {
    id: 'request-1',
    idempotency_key: '11111111-1111-4111-8111-111111111111',
    requester: {
      id: manager.id,
      username: manager.username,
      display_name: manager.display_name,
    },
    recruiter: {
      id: recruiter.id,
      username: recruiter.username,
      display_name: recruiter.display_name,
    },
    created_by: {
      id: manager.id,
      username: manager.username,
      display_name: manager.display_name,
    },
    status: 'draft',
    current_version_number: currentVersion.version_number,
    current_version: currentVersion,
    linked_job_id: null,
    versions: [currentVersion],
    approvals: [],
    created_at: '2026-07-28T08:00:00Z',
    updated_at: '2026-07-28T08:00:00Z',
    ...overrides,
  }
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage(user: AuthUser) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={{ ...authBase, user }}>
        <MemoryRouter>
          <RecruitmentRequestPage />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

describe('招聘需求流程', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('用人经理创建草稿并提交审批', async () => {
    let records: RecruitmentRequestRecord[] = []
    const bodies: unknown[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = input.toString()
        if (path === '/api/recruitment-requests' && !init?.method) {
          return jsonResponse(records)
        }
        if (path === '/api/users/options?role=recruiter') {
          return jsonResponse([recruiter])
        }
        if (path === '/api/recruitment-requests' && init?.method === 'POST') {
          const body = JSON.parse(init.body as string) as Record<string, unknown>
          bodies.push(body)
          const created = requestRecord({
            idempotency_key: body.idempotency_key as string,
            current_version: version({
              job_title: body.job_title as string,
              headcount: body.headcount as number,
              reason: body.reason as string,
              priority: body.priority as 'high',
              target_start_date: body.target_start_date as string,
              salary_min: body.salary_min as number,
              salary_max: body.salary_max as number,
              notes: body.notes as string,
            }),
          })
          records = [created]
          return jsonResponse(created, 201)
        }
        if (path === '/api/recruitment-requests/request-1/submit') {
          bodies.push(JSON.parse(init?.body as string))
          records = [{ ...records[0], status: 'pending_approval' }]
          return jsonResponse(records[0])
        }
        return jsonResponse({ detail: 'not found' }, 404)
      }),
    )

    renderPage(manager)
    expect(await screen.findByText('暂无招聘需求')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /新建需求/ }))

    fireEvent.mouseDown(screen.getByRole('combobox', { name: '负责招聘专员' }))
    fireEvent.click(await screen.findByText('招聘专员（recruiter）'))
    fireEvent.change(screen.getByLabelText('职位名称'), {
      target: { value: '高级后端工程师' },
    })
    fireEvent.change(screen.getByLabelText('招聘人数'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('月薪下限'), { target: { value: '25000' } })
    fireEvent.change(screen.getByLabelText('月薪上限'), { target: { value: '35000' } })
    fireEvent.change(screen.getByLabelText('招聘原因'), {
      target: { value: '核心平台扩容' },
    })
    fireEvent.click(screen.getByRole('button', { name: '创建草稿' }))

    expect((await screen.findAllByText('V1')).length).toBeGreaterThan(0)
    expect(bodies[0]).toMatchObject({
      recruiter_id: recruiter.id,
      job_title: '高级后端工程师',
      headcount: 2,
      salary_min: 25000,
      salary_max: 35000,
    })
    expect((bodies[0] as { idempotency_key: string }).idempotency_key).toMatch(
      /^[0-9a-f-]{36}$/,
    )

    fireEvent.click(screen.getByRole('button', { name: /提交审批/ }))
    fireEvent.click(await screen.findByRole('button', { name: '确认提交' }))
    await waitFor(() => expect(bodies[1]).toEqual({ version_id: 'version-1' }))
    expect((await screen.findAllByText('审批中')).length).toBeGreaterThan(0)
  })

  it('审批人查看审批历史并批准需求', async () => {
    let record = requestRecord({ status: 'pending_approval' })
    let decisionBody: Record<string, unknown> | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = input.toString()
        if (path === '/api/recruitment-requests' && !init?.method) {
          return jsonResponse([record])
        }
        if (path === '/api/recruitment-requests/request-1/decision') {
          decisionBody = JSON.parse(init?.body as string) as Record<string, unknown>
          record = {
            ...record,
            status: 'approved',
            approvals: [
              {
                id: 'approval-1',
                version_id: 'version-1',
                approver_id: approver.id,
                approver_username: approver.username,
                approver_display_name: approver.display_name,
                decision: 'approved',
                comment: decisionBody.comment as string,
                decided_at: '2026-07-28T09:00:00Z',
              },
            ],
          }
          return jsonResponse(record)
        }
        return jsonResponse({ detail: 'not found' }, 404)
      }),
    )

    renderPage(approver)
    fireEvent.click(await screen.findByRole('button', { name: /查看/ }))
    expect(screen.getByText('尚无审批记录')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /批准/ }))
    fireEvent.change(screen.getByLabelText('审批意见'), {
      target: { value: '招聘理由充分' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认批准' }))

    await waitFor(() =>
      expect(decisionBody).toEqual({
        version_id: 'version-1',
        decision: 'approved',
        comment: '招聘理由充分',
      }),
    )
    expect(await screen.findByText('招聘理由充分')).toBeInTheDocument()
    expect(screen.getAllByText('已批准').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /创建关联职位/ })).not.toBeInTheDocument()
  })

  it('被驳回需求通过新版本修改后才能重新提交', async () => {
    const rejected = requestRecord({
      status: 'rejected',
      approvals: [
        {
          id: 'approval-1',
          version_id: 'version-1',
          approver_id: approver.id,
          approver_username: approver.username,
          approver_display_name: approver.display_name,
          decision: 'rejected',
          comment: '请调整到岗日期',
          decided_at: '2026-07-28T09:00:00Z',
        },
      ],
    })
    let record = rejected
    let savedBody: Record<string, unknown> | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = input.toString()
        if (path === '/api/recruitment-requests' && !init?.method) {
          return jsonResponse([record])
        }
        if (path === '/api/users/options?role=recruiter') return jsonResponse([recruiter])
        if (path === '/api/recruitment-requests/request-1/versions') {
          savedBody = JSON.parse(init?.body as string) as Record<string, unknown>
          const nextVersion = version({
            id: 'version-2',
            version_number: 2,
            source_version_id: 'version-1',
            target_start_date: savedBody.target_start_date as string,
          })
          record = requestRecord({
            status: 'draft',
            current_version_number: 2,
            current_version: nextVersion,
            versions: [version(), nextVersion],
            approvals: rejected.approvals,
          })
          return jsonResponse(record, 201)
        }
        return jsonResponse({ detail: 'not found' }, 404)
      }),
    )

    renderPage(manager)
    fireEvent.click(await screen.findByRole('button', { name: /查看/ }))
    expect(screen.getByText('请调整到岗日期')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /提交审批/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /新建修改版本/ }))
    fireEvent.change(screen.getByLabelText('期望到岗日期'), {
      target: { value: '2026-10-15' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存新版本' }))

    await waitFor(() =>
      expect(savedBody).toMatchObject({
        source_version_id: 'version-1',
        target_start_date: '2026-10-15',
      }),
    )
    expect((await screen.findAllByText('V2')).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /提交审批/ })).toBeInTheDocument()
  })

  it('指定招聘专员将已批准需求创建为唯一关联职位', async () => {
    let record = requestRecord({ status: 'approved' })
    let jobBody: Record<string, unknown> | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = input.toString()
        if (path === '/api/recruitment-requests' && !init?.method) {
          return jsonResponse([record])
        }
        if (path === '/api/recruitment-requests/request-1/job') {
          jobBody = JSON.parse(init?.body as string) as Record<string, unknown>
          record = { ...record, status: 'converted', linked_job_id: 'job-1' }
          return jsonResponse(
            {
              id: 'job-1',
              recruiter_id: recruiter.id,
              hiring_manager_id: manager.id,
              recruitment_request_id: record.id,
              title: record.current_version.job_title,
              department: jobBody.department,
              original_jd: jobBody.original_jd,
              status: 'active',
              archived_at: null,
              created_at: '2026-07-28T10:00:00Z',
              updated_at: '2026-07-28T10:00:00Z',
            },
            201,
          )
        }
        return jsonResponse({ detail: 'not found' }, 404)
      }),
    )

    renderPage(recruiter)
    fireEvent.click(await screen.findByRole('button', { name: /查看/ }))
    fireEvent.click(screen.getByRole('button', { name: /创建关联职位/ }))
    expect(screen.getByText('职位名称：高级后端工程师')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('展示分组'), {
      target: { value: '研发中心' },
    })
    fireEvent.change(screen.getByLabelText('原始 JD'), {
      target: { value: '负责核心平台服务设计、开发和稳定性建设。' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认创建' }))

    await waitFor(() =>
      expect(jobBody).toEqual({
        department: '研发中心',
        original_jd: '负责核心平台服务设计、开发和稳定性建设。',
      }),
    )
    expect((await screen.findAllByText('已转职位')).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /查看关联职位/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /创建关联职位/ })).not.toBeInTheDocument()
  })
})
