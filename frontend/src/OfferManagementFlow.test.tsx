import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { AuthUser, OfferRecord, OfferStatus, OfferVersion } from './api/client'

const timestamp = '2026-07-28T08:00:00Z'
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
  approver: {
    id: 'approver-1',
    username: 'approver',
    display_name: '审批人',
    is_active: true,
    must_change_password: false,
    roles: ['approver'],
  },
}

function version(overrides: Partial<OfferVersion> = {}): OfferVersion {
  return {
    id: 'version-1',
    version_number: 1,
    idempotency_key: 'version-key',
    submission_idempotency_key: null,
    submitted_at: null,
    source_version_id: null,
    source_interview_report_version_id: 'report-version-1',
    currency: 'CNY',
    monthly_salary: '30000.00',
    annual_salary_months: '14.00',
    probation_months: 3,
    probation_monthly_salary: '27000.00',
    bonus_description: '年度奖金另计',
    expected_start_date: '2026-09-01',
    valid_until: '2026-08-15',
    notes: '仅授权人员可见',
    created_by_id: 'recruiter-1',
    created_by_username: 'recruiter',
    created_by_display_name: '招聘专员',
    created_at: timestamp,
    manager_confirmation: null,
    approval: null,
    ...overrides,
  }
}

function offerRecord(
  status: OfferStatus,
  currentVersion: OfferVersion = version(),
): OfferRecord {
  return {
    id: 'offer-1',
    application_id: 'application-1',
    application_status: 'active',
    job_id: job.id,
    job_title: job.title,
    candidate_id: 'candidate-1',
    candidate_code: 'CAND-0001',
    candidate_name: '候选人A',
    status,
    current_version_number: currentVersion.version_number,
    current_version: currentVersion,
    versions: [currentVersion],
    created_by_id: 'recruiter-1',
    created_at: timestamp,
    updated_at: timestamp,
  }
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

function commonResponse(path: string, user: AuthUser, offers: OfferRecord[]) {
  if (path === '/api/auth/me') return jsonResponse(user)
  if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
  if (path === '/api/jobs?include_archived=true') return jsonResponse([job])
  if (path === '/api/offers') return jsonResponse(offers)
  return undefined
}

async function findModalByTitle(title: string) {
  const matches = await screen.findAllByText(title)
  const dialog = matches
    .map((match) => match.closest('.ant-modal[role="dialog"]'))
    .find((candidate): candidate is HTMLElement => candidate instanceof HTMLElement)
  if (!dialog) throw new Error(`未找到标题为“${title}”的弹窗`)
  return dialog
}

describe('Offer management flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('招聘专员从录用报告创建并提交 Offer 草稿', async () => {
    let saved: OfferRecord | null = null
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      const common = commonResponse(path, users.recruiter, saved ? [saved] : [])
      if (common) return common
      if (
        path === '/api/jobs/job-1/applications/application-1/offer' &&
        method === 'POST'
      ) {
        saved = offerRecord('draft')
        return jsonResponse(saved, 201)
      }
      if (path === '/api/offers/offer-1/submit' && method === 'POST') {
        saved = offerRecord('pending_manager_confirmation', {
          ...version(),
          submission_idempotency_key: 'submit-key',
          submitted_at: timestamp,
        })
        return jsonResponse(saved)
      }
      if (path === '/api/offers/offer-1') return jsonResponse(saved)
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/offers?create=1&jobId=job-1&applicationId=application-1')

    expect(await screen.findByRole('dialog', { name: '创建 Offer 草稿' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }))
    expect(await screen.findByText('Offer 草稿已创建')).toBeInTheDocument()
    expect(await screen.findByText('当前薪酬方案')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '提交确认' }))
    const submitDialog = await findModalByTitle('提交用人经理确认？')
    fireEvent.click(within(submitDialog).getByRole('button', { name: /提\s*交/ }))
    expect(await screen.findByText('Offer 已提交用人经理确认')).toBeInTheDocument()
    expect((await screen.findAllByText('待经理确认')).length).toBeGreaterThan(0)
    expect(await screen.findByText('参考年薪')).toBeInTheDocument()
    expect(await screen.findByText('420,000 元/年')).toBeInTheDocument()

    const createCall = fetchMock.mock.calls.find(
      ([path, init]) =>
        path === '/api/jobs/job-1/applications/application-1/offer' &&
        (init as RequestInit | undefined)?.method === 'POST',
    )
    expect(createCall).toBeDefined()
    expect(JSON.parse((createCall?.[1] as RequestInit).body as string)).toMatchObject({
      monthly_salary: 30000,
      annual_salary_months: 12,
      probation_months: 3,
    })
  })

  it('用人经理确认录用并把 Offer 推入最终审批', async () => {
    let saved = offerRecord('pending_manager_confirmation', {
      ...version(),
      submission_idempotency_key: 'submit-key',
      submitted_at: timestamp,
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      const common = commonResponse(path, users.manager, [saved])
      if (common) return common
      if (path === '/api/offers/offer-1') return jsonResponse(saved)
      if (path === '/api/offers/offer-1/manager-decision' && method === 'POST') {
        saved = offerRecord('pending_approval', {
          ...saved.current_version,
          manager_confirmation: {
            id: 'manager-decision-1',
            idempotency_key: 'manager-key',
            confirmer_id: users.manager.id,
            confirmer_username: users.manager.username,
            confirmer_display_name: users.manager.display_name,
            decision: 'confirmed',
            comment: '确认录用',
            decided_at: timestamp,
          },
        })
        return jsonResponse(saved)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/offers')

    fireEvent.click(await screen.findByRole('button', { name: '查看 候选人A 的 Offer' }))
    fireEvent.click(await screen.findByRole('button', { name: '确认录用' }))
    const dialog = await findModalByTitle('确认录用')
    fireEvent.change(within(dialog).getByLabelText('处理意见'), {
      target: { value: '确认录用' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: /确\s*认/ }))

    expect(await screen.findByText('录用已确认')).toBeInTheDocument()
    expect((await screen.findAllByText('待最终审批')).length).toBeGreaterThan(0)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/offers/offer-1/manager-decision',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('独立审批人批准 Offer 并保留审批意见', async () => {
    const managerConfirmation: OfferVersion['manager_confirmation'] = {
      id: 'manager-decision-1',
      idempotency_key: 'manager-key',
      confirmer_id: users.manager.id,
      confirmer_username: users.manager.username,
      confirmer_display_name: users.manager.display_name,
      decision: 'confirmed',
      comment: '确认录用',
      decided_at: timestamp,
    }
    let saved = offerRecord('pending_approval', {
      ...version(),
      submission_idempotency_key: 'submit-key',
      submitted_at: timestamp,
      manager_confirmation: managerConfirmation,
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      const common = commonResponse(path, users.approver, [saved])
      if (common) return common
      if (path === '/api/offers/offer-1') return jsonResponse(saved)
      if (path === '/api/offers/offer-1/approval-decision' && method === 'POST') {
        saved = offerRecord('approved', {
          ...saved.current_version,
          approval: {
            id: 'approval-1',
            idempotency_key: 'approval-key',
            approver_id: users.approver.id,
            approver_username: users.approver.username,
            approver_display_name: users.approver.display_name,
            decision: 'approved',
            comment: '审批通过',
            decided_at: timestamp,
          },
        })
        return jsonResponse(saved)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/offers')

    fireEvent.click(await screen.findByRole('button', { name: '查看 候选人A 的 Offer' }))
    fireEvent.click(await screen.findByRole('button', { name: '批准 Offer' }))
    const dialog = await findModalByTitle('批准 Offer')
    fireEvent.change(within(dialog).getByLabelText('处理意见'), {
      target: { value: '审批通过' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: /确\s*认/ }))

    expect(await screen.findByText('Offer 已批准')).toBeInTheDocument()
    expect(await screen.findByText('审批意见：审批通过')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/offers/offer-1/approval-decision',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('招聘专员生成并一次性复制候选人门户链接', async () => {
    let saved = offerRecord('approved', {
      ...version(),
      approval: {
        id: 'approval-1',
        idempotency_key: 'approval-key',
        approver_id: users.approver.id,
        approver_username: users.approver.username,
        approver_display_name: users.approver.display_name,
        decision: 'approved',
        comment: '审批通过',
        decided_at: timestamp,
      },
    })
    let links: Array<Record<string, unknown>> = []
    const copyText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...window.navigator, clipboard: { writeText: copyText } })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      const common = commonResponse(path, users.recruiter, [saved])
      if (common) return common
      if (path === '/api/offers/offer-1') return jsonResponse(saved)
      if (path === '/api/offers/offer-1/portal-links' && method === 'GET') {
        return jsonResponse(links)
      }
      if (path === '/api/offers/offer-1/portal-links' && method === 'POST') {
        saved = offerRecord('pending_response', saved.current_version)
        links = [
          {
            id: 'link-1',
            version_id: 'version-1',
            state: 'active',
            expires_at: '2026-08-15T15:59:59Z',
            created_by_username: 'recruiter',
            created_by_display_name: '招聘专员',
            created_at: timestamp,
            revoked_at: null,
            revoked_by_username: null,
            revoked_by_display_name: null,
            revocation_reason: null,
          },
        ]
        return jsonResponse({ ...links[0], portal_token: 'p'.repeat(48) }, 201)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/offers')

    fireEvent.click(await screen.findByRole('button', { name: '查看 候选人A 的 Offer' }))
    fireEvent.click(await screen.findByRole('button', { name: /生成候选人链接/ }))

    const issuedInput = await screen.findByRole('textbox', {
      name: '新生成的候选人链接',
    })
    expect(issuedInput).toHaveValue(`${window.location.origin}/offer#${'p'.repeat(48)}`)
    fireEvent.click(screen.getByRole('button', { name: /复制链接/ }))
    await waitFor(() => {
      expect(copyText).toHaveBeenCalledWith(
        `${window.location.origin}/offer#${'p'.repeat(48)}`,
      )
      expect(
        screen.queryByRole('textbox', { name: '新生成的候选人链接' }),
      ).not.toBeInTheDocument()
    })
    expect(await screen.findByText('有效')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重新生成/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /撤回链接/ })).toBeInTheDocument()
  })

  it('招聘专员填写原因后重新生成并撤回候选人链接', async () => {
    const approvedVersion = {
      ...version(),
      approval: {
        id: 'approval-1',
        idempotency_key: 'approval-key',
        approver_id: users.approver.id,
        approver_username: users.approver.username,
        approver_display_name: users.approver.display_name,
        decision: 'approved' as const,
        comment: '审批通过',
        decided_at: timestamp,
      },
    }
    let saved = offerRecord('pending_response', approvedVersion)
    const oldLink = {
      id: 'link-1',
      version_id: 'version-1',
      state: 'active',
      expires_at: '2026-08-15T15:59:59Z',
      created_by_username: 'recruiter',
      created_by_display_name: '招聘专员',
      created_at: timestamp,
      revoked_at: null,
      revoked_by_username: null,
      revoked_by_display_name: null,
      revocation_reason: null,
    }
    let links: Array<Record<string, unknown>> = [oldLink]
    const operationPayloads: Array<Record<string, unknown>> = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      const common = commonResponse(path, users.recruiter, [saved])
      if (common) return common
      if (path === '/api/offers/offer-1') return jsonResponse(saved)
      if (path === '/api/offers/offer-1/portal-links' && method === 'GET') {
        return jsonResponse(links)
      }
      if (path === '/api/offers/offer-1/portal-links/regenerate' && method === 'POST') {
        operationPayloads.push(JSON.parse(init?.body as string) as Record<string, unknown>)
        const revokedOld = {
          ...oldLink,
          state: 'revoked',
          revoked_at: '2026-07-28T09:00:00Z',
          revoked_by_username: 'recruiter',
          revoked_by_display_name: '招聘专员',
          revocation_reason: '候选人未收到旧链接',
        }
        const replacement = {
          ...oldLink,
          id: 'link-2',
          created_at: '2026-07-28T09:00:00Z',
        }
        links = [replacement, revokedOld]
        return jsonResponse({ ...replacement, portal_token: 'q'.repeat(48) }, 201)
      }
      if (path === '/api/offers/offer-1/portal-links/link-2/revoke' && method === 'POST') {
        operationPayloads.push(JSON.parse(init?.body as string) as Record<string, unknown>)
        links = [
          {
            ...links[0],
            state: 'revoked',
            revoked_at: '2026-07-28T10:00:00Z',
            revoked_by_username: 'recruiter',
            revoked_by_display_name: '招聘专员',
            revocation_reason: '候选人决定暂缓',
          },
          links[1],
        ]
        saved = offerRecord('approved', approvedVersion)
        return jsonResponse(links[0])
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/offers')

    fireEvent.click(await screen.findByRole('button', { name: '查看 候选人A 的 Offer' }))
    fireEvent.click(await screen.findByRole('button', { name: /重新生成/ }))
    const regenerateDialog = await findModalByTitle('重新生成候选人链接')
    fireEvent.change(within(regenerateDialog).getByLabelText('操作原因'), {
      target: { value: '候选人未收到旧链接' },
    })
    fireEvent.click(
      within(regenerateDialog).getByRole('button', { name: /确认重新生成/ }),
    )

    expect(await screen.findByText('候选人链接已重新生成，旧链接已失效')).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: /撤回链接/ }))
    const revokeDialog = await findModalByTitle('撤回候选人链接')
    fireEvent.change(within(revokeDialog).getByLabelText('操作原因'), {
      target: { value: '候选人决定暂缓' },
    })
    fireEvent.click(within(revokeDialog).getByRole('button', { name: /确认撤回/ }))

    expect(await screen.findByText('候选人链接已撤回')).toBeInTheDocument()
    expect(operationPayloads).toHaveLength(2)
    expect(operationPayloads[0]).toMatchObject({ reason: '候选人未收到旧链接' })
    expect(operationPayloads[1]).toMatchObject({ reason: '候选人决定暂缓' })
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /撤回链接/ })).not.toBeInTheDocument()
    })
  })
})
