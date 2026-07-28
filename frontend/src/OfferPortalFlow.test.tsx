import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { CandidateOfferViewRecord, OfferPortalVerifiedRecord } from './api/client'

const token = 'p'.repeat(48)
const verificationToken = 'v'.repeat(48)
const timestamp = '2026-07-29T08:00:00Z'

const pendingOffer: CandidateOfferViewRecord = {
  candidate_name: '张三',
  job_title: '高级后端工程师',
  progress: 'offer_pending_response',
  currency: 'CNY',
  monthly_salary: '30000.00',
  annual_salary_months: '14.00',
  probation_months: 3,
  probation_monthly_salary: '27000.00',
  bonus_description: '年度奖金另计',
  expected_start_date: '2026-09-01',
  valid_until: '2026-08-15',
  notes: '请在有效期内确认',
  response: null,
  onboarding: null,
}

const verifiedOffer: OfferPortalVerifiedRecord = {
  ...pendingOffer,
  verification_token: verificationToken,
  verification_expires_at: '2026-07-29T08:15:00Z',
}

const acceptedOffer: CandidateOfferViewRecord = {
  ...pendingOffer,
  progress: 'accepted',
  response: {
    decision: 'accepted',
    rejection_reason_code: null,
    rejection_note: null,
    responded_at: timestamp,
  },
  onboarding: {
    status: 'pending_confirmation',
    version: 1,
    action_owner: 'candidate',
    expected_start_date: '2026-09-01',
    candidate_proposed_date: null,
    recruiter_proposed_date: null,
    confirmed_start_date: null,
    actual_start_date: null,
    abandonment_source: null,
    abandonment_reason_code: null,
  },
}

function verified(record: CandidateOfferViewRecord): OfferPortalVerifiedRecord {
  return {
    ...record,
    verification_token: verificationToken,
    verification_expires_at: '2026-07-29T08:15:00Z',
  }
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPortal(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  window.history.replaceState({}, '', `/offer#${token}`)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

function authResponse(path: string) {
  if (path === '/api/auth/me') return jsonResponse({ detail: '请先登录' }, 401)
  return undefined
}

async function verifyCandidate() {
  expect(await screen.findByRole('heading', { name: '验证身份' })).toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox', { name: '手机号后四位' }), {
    target: { value: '5678' },
  })
  fireEvent.click(screen.getByRole('button', { name: '验证并查看 Offer' }))
  expect(
    await screen.findByRole('heading', { name: '高级后端工程师' }),
  ).toBeInTheDocument()
}

describe('candidate Offer portal', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('清除地址栏令牌并完成验证与接受回应', async () => {
    let responsePayload: Record<string, unknown> | undefined
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const auth = authResponse(path)
      if (auth) return auth
      if (path === '/api/portal/offers/status') {
        return jsonResponse({ status: 'verification_required' })
      }
      if (path === '/api/portal/offers/verify') return jsonResponse(verifiedOffer)
      if (path === '/api/portal/offers/respond') {
        responsePayload = JSON.parse(init?.body as string) as Record<string, unknown>
        return jsonResponse({
          ...pendingOffer,
          progress: 'accepted',
          response: {
            decision: 'accepted',
            rejection_reason_code: null,
            rejection_note: null,
            responded_at: timestamp,
          },
        })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderPortal(fetchMock)

    await verifyCandidate()
    expect(window.location.hash).toBe('')
    expect(
      fetchMock.mock.calls.some(([input]) => input.toString() === '/api/auth/me'),
    ).toBe(false)
    expect(screen.queryByRole('navigation', { name: '主导航' })).not.toBeInTheDocument()
    expect(screen.getByText('420,000 元/年')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /接受 Offer/ }))
    const dialog = await screen.findByRole('dialog', { name: '确认接受 Offer' })
    fireEvent.click(within(dialog).getByRole('button', { name: '确认接受' }))

    expect(await screen.findByRole('heading', { name: '您已接受 Offer' })).toBeInTheDocument()
    expect(responsePayload).toMatchObject({
      token,
      verification_token: verificationToken,
      decision: 'accepted',
      rejection_reason_code: null,
      rejection_note: null,
    })
    expect(screen.queryByRole('button', { name: /拒绝 Offer/ })).not.toBeInTheDocument()
  })

  it('要求结构化拒绝原因并在回应后只读展示', async () => {
    let responsePayload: Record<string, unknown> | undefined
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const auth = authResponse(path)
      if (auth) return auth
      if (path === '/api/portal/offers/status') {
        return jsonResponse({ status: 'verification_required' })
      }
      if (path === '/api/portal/offers/verify') return jsonResponse(verifiedOffer)
      if (path === '/api/portal/offers/respond') {
        responsePayload = JSON.parse(init?.body as string) as Record<string, unknown>
        return jsonResponse({
          ...pendingOffer,
          progress: 'declined',
          response: {
            decision: 'rejected',
            rejection_reason_code: 'career',
            rejection_note: '选择了其他发展方向',
            responded_at: timestamp,
          },
        })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderPortal(fetchMock)

    await verifyCandidate()
    fireEvent.click(screen.getByRole('button', { name: '拒绝 Offer' }))
    const dialog = await screen.findByRole('dialog', { name: '确认拒绝 Offer' })
    fireEvent.mouseDown(within(dialog).getByRole('combobox', { name: '拒绝原因' }))
    fireEvent.click(await screen.findByText('职业发展'))
    fireEvent.change(within(dialog).getByRole('textbox', { name: '补充说明' }), {
      target: { value: '选择了其他发展方向' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: '确认拒绝' }))

    expect(await screen.findByRole('heading', { name: '您已拒绝 Offer' })).toBeInTheDocument()
    expect(screen.getByText('拒绝原因：职业发展')).toBeInTheDocument()
    expect(screen.getByText('补充说明：选择了其他发展方向')).toBeInTheDocument()
    expect(responsePayload).toMatchObject({
      decision: 'rejected',
      rejection_reason_code: 'career',
      rejection_note: '选择了其他发展方向',
    })
  })

  it('对已撤回或过期的链接显示终止状态', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const auth = authResponse(path)
      if (auth) return auth
      if (path === '/api/portal/offers/status') {
        return jsonResponse({ detail: '候选人链接已撤回' }, 410)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderPortal(fetchMock)

    expect(await screen.findByText('链接已失效')).toBeInTheDocument()
    expect(screen.getByText('候选人链接已撤回')).toBeInTheDocument()
    expect(window.location.hash).toBe('')
  })

  it('验证服务恢复后可重新加载链接状态', async () => {
    let statusAttempts = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const auth = authResponse(path)
      if (auth) return auth
      if (path === '/api/portal/offers/status') {
        statusAttempts += 1
        return statusAttempts === 1
          ? jsonResponse({ detail: '候选人验证服务暂时不可用，请稍后重试' }, 503)
          : jsonResponse({ status: 'verification_required' })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderPortal(fetchMock)

    expect(await screen.findByText('验证服务暂不可用')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /重新加载/ }))
    expect(await screen.findByRole('heading', { name: '验证身份' })).toBeInTheDocument()
    expect(statusAttempts).toBe(2)
  })

  it('连续验证失败锁定后保留明确错误状态', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const auth = authResponse(path)
      if (auth) return auth
      if (path === '/api/portal/offers/status') {
        return jsonResponse({ status: 'verification_required' })
      }
      if (path === '/api/portal/offers/verify') {
        return jsonResponse({ detail: '验证失败次数过多，请稍后重试' }, 429)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderPortal(fetchMock)

    expect(await screen.findByRole('heading', { name: '验证身份' })).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: '手机号后四位' }), {
      target: { value: '0000' },
    })
    fireEvent.click(screen.getByRole('button', { name: '验证并查看 Offer' }))

    expect(await screen.findByText('验证暂时锁定')).toBeInTheDocument()
    expect(screen.getByText('验证失败次数过多，请稍后重试')).toBeInTheDocument()
    await waitFor(() => expect(window.location.hash).toBe(''))
  })

  it('回应时验证会话过期会返回身份验证页', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const auth = authResponse(path)
      if (auth) return auth
      if (path === '/api/portal/offers/status') {
        return jsonResponse({ status: 'verification_required' })
      }
      if (path === '/api/portal/offers/verify') return jsonResponse(verifiedOffer)
      if (path === '/api/portal/offers/respond') {
        return jsonResponse({ detail: '候选人验证已失效，请重新验证' }, 401)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderPortal(fetchMock)

    await verifyCandidate()
    fireEvent.click(screen.getByRole('button', { name: /接受 Offer/ }))
    const dialog = await screen.findByRole('dialog', { name: '确认接受 Offer' })
    fireEvent.click(within(dialog).getByRole('button', { name: '确认接受' }))

    expect(await screen.findByText('身份验证已失效，请重新验证')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '验证身份' })).toBeInTheDocument()
  })

  it('并发回应冲突时读取并展示已经生效的结果', async () => {
    const declinedOffer: CandidateOfferViewRecord = {
      ...pendingOffer,
      progress: 'declined',
      response: {
        decision: 'rejected',
        rejection_reason_code: 'timing',
        rejection_note: '入职时间无法协调',
        responded_at: timestamp,
      },
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const auth = authResponse(path)
      if (auth) return auth
      if (path === '/api/portal/offers/status') {
        return jsonResponse({ status: 'verification_required' })
      }
      if (path === '/api/portal/offers/verify') return jsonResponse(verifiedOffer)
      if (path === '/api/portal/offers/respond') {
        return jsonResponse({ detail: '候选人已经完成不同的 Offer 回应' }, 409)
      }
      if (path === '/api/portal/offers/detail') return jsonResponse(declinedOffer)
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderPortal(fetchMock)

    await verifyCandidate()
    fireEvent.click(screen.getByRole('button', { name: /接受 Offer/ }))
    const dialog = await screen.findByRole('dialog', { name: '确认接受 Offer' })
    fireEvent.click(within(dialog).getByRole('button', { name: '确认接受' }))

    expect(await screen.findByText('Offer 状态已由其他操作更新')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '您已拒绝 Offer' })).toBeInTheDocument()
    expect(screen.getByText('拒绝原因：入职时间')).toBeInTheDocument()
  })

  it('已接受 Offer 后确认招聘方提出的入职日期并携带最新版本', async () => {
    let confirmPayload: Record<string, unknown> | undefined
    const recruiterProposedOffer: CandidateOfferViewRecord = {
      ...acceptedOffer,
      onboarding: {
        ...acceptedOffer.onboarding!,
        version: 4,
        recruiter_proposed_date: '2026-09-08',
      },
    }
    const confirmedOffer: CandidateOfferViewRecord = {
      ...recruiterProposedOffer,
      onboarding: {
        ...recruiterProposedOffer.onboarding!,
        status: 'pending_start',
        version: 5,
        action_owner: 'recruiter',
        confirmed_start_date: '2026-09-08',
      },
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const auth = authResponse(path)
      if (auth) return auth
      if (path === '/api/portal/offers/status') {
        return jsonResponse({ status: 'verification_required' })
      }
      if (path === '/api/portal/offers/verify') return jsonResponse(verified(recruiterProposedOffer))
      if (path === '/api/portal/offers/onboarding/confirm-date') {
        confirmPayload = JSON.parse(init?.body as string) as Record<string, unknown>
        return jsonResponse(confirmedOffer)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderPortal(fetchMock)

    await verifyCandidate()
    expect(screen.getByRole('heading', { name: '入职确认' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /确认入职日期/ }))
    const dialog = await screen.findByRole('dialog', { name: '确认入职日期' })
    expect(within(dialog).getByText(/2026\/09\/08/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: '确认提交' }))

    expect(await screen.findByText('入职日期已确认')).toBeInTheDocument()
    expect(screen.getByText(/确认日期：2026\/09\/08/)).toBeInTheDocument()
    expect(confirmPayload).toMatchObject({
      token,
      verification_token: verificationToken,
      version: 4,
      start_date: '2026-09-08',
    })
    expect(confirmPayload?.idempotency_key).toEqual(expect.any(String))
  })

  it('提出其他入职日期时校验日期和说明并进入等待招聘方状态', async () => {
    let proposalPayload: Record<string, unknown> | undefined
    const proposedOffer: CandidateOfferViewRecord = {
      ...acceptedOffer,
      onboarding: {
        ...acceptedOffer.onboarding!,
        status: 'candidate_proposed_date',
        version: 2,
        action_owner: 'recruiter',
        candidate_proposed_date: '2026-09-15',
      },
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const auth = authResponse(path)
      if (auth) return auth
      if (path === '/api/portal/offers/status') {
        return jsonResponse({ status: 'verification_required' })
      }
      if (path === '/api/portal/offers/verify') return jsonResponse(verified(acceptedOffer))
      if (path === '/api/portal/offers/onboarding/propose-date') {
        proposalPayload = JSON.parse(init?.body as string) as Record<string, unknown>
        return jsonResponse(proposedOffer)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderPortal(fetchMock)

    await verifyCandidate()
    fireEvent.click(screen.getByRole('button', { name: '提出其他日期' }))
    const dialog = await screen.findByRole('dialog', { name: '提出其他入职日期' })
    fireEvent.click(within(dialog).getByRole('button', { name: '确认提交' }))
    expect(await within(dialog).findByText('请选择日期')).toBeInTheDocument()
    expect(within(dialog).getByText('请填写说明')).toBeInTheDocument()

    fireEvent.change(within(dialog).getByLabelText('其他入职日期'), {
      target: { value: '2026-09-15' },
    })
    fireEvent.change(within(dialog).getByRole('textbox', { name: '调整说明' }), {
      target: { value: '需要完成当前项目交接' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: '确认提交' }))

    expect(await screen.findByText('招聘专员正在确认您提出的日期')).toBeInTheDocument()
    expect(screen.getByText(/您提出的日期：2026\/09\/15/)).toBeInTheDocument()
    expect(proposalPayload).toMatchObject({
      token,
      verification_token: verificationToken,
      version: 1,
      start_date: '2026-09-15',
      note: '需要完成当前项目交接',
    })
  })

  it('正式入职前可提交结构化放弃原因和说明', async () => {
    let abandonPayload: Record<string, unknown> | undefined
    const pendingStartOffer: CandidateOfferViewRecord = {
      ...acceptedOffer,
      onboarding: {
        ...acceptedOffer.onboarding!,
        status: 'pending_start',
        version: 3,
        action_owner: 'recruiter',
        confirmed_start_date: '2026-09-01',
      },
    }
    const abandonedOffer: CandidateOfferViewRecord = {
      ...pendingStartOffer,
      onboarding: {
        ...pendingStartOffer.onboarding!,
        status: 'abandoned',
        version: 4,
        action_owner: 'none',
        abandonment_source: 'candidate_withdrew',
        abandonment_reason_code: 'personal',
      },
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const auth = authResponse(path)
      if (auth) return auth
      if (path === '/api/portal/offers/status') {
        return jsonResponse({ status: 'verification_required' })
      }
      if (path === '/api/portal/offers/verify') return jsonResponse(verified(pendingStartOffer))
      if (path === '/api/portal/offers/onboarding/abandon') {
        abandonPayload = JSON.parse(init?.body as string) as Record<string, unknown>
        return jsonResponse(abandonedOffer)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderPortal(fetchMock)

    await verifyCandidate()
    fireEvent.click(screen.getByRole('button', { name: '无法按计划入职' }))
    const dialog = await screen.findByRole('dialog', { name: '确认无法入职' })
    fireEvent.change(within(dialog).getByRole('textbox', { name: '详细说明' }), {
      target: { value: '个人计划发生变化' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: '确认放弃入职' }))

    expect(await screen.findByText('入职流程已结束')).toBeInTheDocument()
    expect(screen.getByText('原因：个人原因')).toBeInTheDocument()
    expect(abandonPayload).toMatchObject({
      version: 3,
      reason_code: 'personal',
      note: '个人计划发生变化',
    })
    expect(screen.queryByRole('button', { name: '无法按计划入职' })).not.toBeInTheDocument()
  })

  it.each([
    {
      label: '已入职',
      record: {
        ...acceptedOffer,
        onboarding: {
          ...acceptedOffer.onboarding!,
          status: 'onboarded' as const,
          version: 6,
          action_owner: 'none' as const,
          confirmed_start_date: '2026-09-01',
          actual_start_date: '2026-09-01',
        },
      },
      expectedText: '已完成入职',
    },
    {
      label: '已放弃',
      record: {
        ...acceptedOffer,
        onboarding: {
          ...acceptedOffer.onboarding!,
          status: 'abandoned' as const,
          version: 4,
          action_owner: 'none' as const,
          abandonment_source: 'candidate_withdrew' as const,
          abandonment_reason_code: 'career' as const,
        },
      },
      expectedText: '入职流程已结束',
    },
  ])('$label 状态只读展示', async ({ record, expectedText }) => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const auth = authResponse(path)
      if (auth) return auth
      if (path === '/api/portal/offers/status') {
        return jsonResponse({ status: 'verification_required' })
      }
      if (path === '/api/portal/offers/verify') return jsonResponse(verified(record))
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderPortal(fetchMock)

    await verifyCandidate()
    expect(screen.getByText(expectedText)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /确认入职日期/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '提出其他日期' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '无法按计划入职' })).not.toBeInTheDocument()
  })

  it('入职操作的验证会话过期时返回验证页', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const auth = authResponse(path)
      if (auth) return auth
      if (path === '/api/portal/offers/status') {
        return jsonResponse({ status: 'verification_required' })
      }
      if (path === '/api/portal/offers/verify') return jsonResponse(verified(acceptedOffer))
      if (path === '/api/portal/offers/onboarding/confirm-date') {
        return jsonResponse({ detail: '候选人验证已失效，请重新验证' }, 401)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderPortal(fetchMock)

    await verifyCandidate()
    fireEvent.click(screen.getByRole('button', { name: /确认入职日期/ }))
    const dialog = await screen.findByRole('dialog', { name: '确认入职日期' })
    fireEvent.click(within(dialog).getByRole('button', { name: '确认提交' }))

    expect(await screen.findByText('身份验证已失效，请重新验证')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '验证身份' })).toBeInTheDocument()
  })

  it('入职版本冲突时刷新并展示最新状态', async () => {
    const latestOffer: CandidateOfferViewRecord = {
      ...acceptedOffer,
      onboarding: {
        ...acceptedOffer.onboarding!,
        status: 'pending_start',
        version: 2,
        action_owner: 'recruiter',
        confirmed_start_date: '2026-09-01',
      },
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const auth = authResponse(path)
      if (auth) return auth
      if (path === '/api/portal/offers/status') {
        return jsonResponse({ status: 'verification_required' })
      }
      if (path === '/api/portal/offers/verify') return jsonResponse(verified(acceptedOffer))
      if (path === '/api/portal/offers/onboarding/confirm-date') {
        return jsonResponse({ detail: '入职记录已由其他操作更新' }, 409)
      }
      if (path === '/api/portal/offers/detail') return jsonResponse(latestOffer)
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderPortal(fetchMock)

    await verifyCandidate()
    fireEvent.click(screen.getByRole('button', { name: /确认入职日期/ }))
    const dialog = await screen.findByRole('dialog', { name: '确认入职日期' })
    fireEvent.click(within(dialog).getByRole('button', { name: '确认提交' }))

    expect(await screen.findByText('入职状态已更新，请查看最新结果')).toBeInTheDocument()
    expect(screen.getByText('入职日期已确认')).toBeInTheDocument()
    expect(screen.getByText(/确认日期：2026\/09\/01/)).toBeInTheDocument()
  })
})
