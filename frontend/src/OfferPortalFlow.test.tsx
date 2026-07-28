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
}

const verifiedOffer: OfferPortalVerifiedRecord = {
  ...pendingOffer,
  verification_token: verificationToken,
  verification_expires_at: '2026-07-29T08:15:00Z',
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
})
