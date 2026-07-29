import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type {
  CandidateDetailRecord,
  CandidateDuplicateReviewRecord,
  CandidateListItemRecord,
} from './api/client'

const timestamp = '2026-07-28T08:00:00Z'
const recruiter = {
  id: 'user-1',
  username: 'recruiter',
  display_name: '招聘专员',
  is_active: true,
  must_change_password: false,
  roles: ['recruiter'],
}
const targetCandidate: CandidateListItemRecord = {
  id: 'candidate-1',
  candidate_code: 'CAND-000000000001',
  full_name: '张三',
  phone: null,
  email: 'zhangsan@example.com',
  status: 'active',
  merged_into_candidate_id: null,
  application_count: 1,
  resume_count: 1,
  pending_duplicate_count: 1,
  created_at: timestamp,
  updated_at: timestamp,
}
const sourceCandidate: CandidateListItemRecord = {
  id: 'candidate-2',
  candidate_code: 'CAND-000000000002',
  full_name: '张 三',
  phone: '13800138000',
  email: null,
  status: 'active',
  merged_into_candidate_id: null,
  application_count: 2,
  resume_count: 2,
  pending_duplicate_count: 1,
  created_at: timestamp,
  updated_at: timestamp,
}
const candidateDetail: CandidateDetailRecord = {
  ...targetCandidate,
  applications: [
    {
      id: 'application-1',
      job_id: 'job-1',
      job_title: '后端工程师',
      job_status: 'active',
      status: 'active',
      merged_into_application_id: null,
      current_stage: 'to_interview',
      document_count: 1,
      created_at: timestamp,
    },
  ],
  resumes: [
    {
      id: 'document-1',
      application_id: 'application-1',
      job_id: 'job-1',
      job_title: '后端工程师',
      batch_id: 'batch-1',
      batch_name: '社招第一批',
      original_filename: 'zhang-san.pdf',
      status: 'completed',
      created_at: timestamp,
    },
  ],
}
const review: CandidateDuplicateReviewRecord = {
  id: 'review-1',
  candidate_a: targetCandidate,
  candidate_b: sourceCandidate,
  source_document_id: 'document-2',
  confidence: 'strong',
  signals: ['phone_exact', 'resume_sha256_exact'],
  status: 'pending',
  resolved_by_id: null,
  resolution_note: null,
  resolved_at: null,
  created_at: timestamp,
  updated_at: timestamp,
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderCandidateCenter(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  window.history.replaceState({}, '', '/candidates')
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

function baseResponse(path: string) {
  if (path === '/api/auth/me') return jsonResponse(recruiter)
  if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
  if (path === '/api/jobs?include_archived=true') return jsonResponse([])
  if (path.startsWith('/api/candidates?')) {
    return jsonResponse({
      items: [targetCandidate, sourceCandidate],
      total: 2,
      limit: 20,
      offset: 0,
    })
  }
  if (path === '/api/candidates/candidate-1') return jsonResponse(candidateDetail)
  return undefined
}

describe('candidate center', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('展示候选人主档案并查看跨职位业务详情', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      return baseResponse(path) ?? jsonResponse({ detail: 'not found' }, 404)
    })
    renderCandidateCenter(fetchMock)

    expect(await screen.findByRole('heading', { name: '企业候选人档案' })).toBeInTheDocument()
    expect(await screen.findByText('张三')).toBeInTheDocument()
    expect(screen.getByText('13800138000')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: /查看/ })[0])
    expect(await screen.findByText('张三 · CAND-000000000001')).toBeInTheDocument()
    expect(screen.getAllByText('后端工程师').length).toBeGreaterThan(0)
    expect(screen.getByText('zhang-san.pdf')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'branches 流程' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'eye 资料' })).toBeInTheDocument()
  })

  it('人工选择保留档案并提交合并原因', async () => {
    let pendingReviews = [review]
    let mergePayload: Record<string, unknown> | undefined
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      const base = baseResponse(path)
      if (base) return base
      if (path === '/api/candidates/duplicate-reviews?status=pending' && method === 'GET') {
        return jsonResponse(pendingReviews)
      }
      if (
        path === '/api/candidates/duplicate-reviews/review-1/merge' &&
        method === 'POST'
      ) {
        mergePayload = JSON.parse(init?.body as string) as Record<string, unknown>
        pendingReviews = []
        return jsonResponse({
          review: { ...review, status: 'merged' },
          target_candidate: sourceCandidate,
          merged_candidate: { ...targetCandidate, status: 'merged' },
          moved_application_ids: ['application-1'],
          merged_application_ids: [],
          moved_document_count: 1,
        })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderCandidateCenter(fetchMock)

    fireEvent.click(await screen.findByRole('tab', { name: '重复确认' }))
    expect(await screen.findByText('手机号一致')).toBeInTheDocument()
    expect(screen.getByText('简历文件一致')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /合并档案/ }))
    fireEvent.click(screen.getByRole('radio', { name: /张 三/ }))
    fireEvent.change(screen.getByRole('textbox', { name: '处理原因' }), {
      target: { value: '人工核对电话和工作经历后确认是同一人' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认合并' }))

    expect(await screen.findByText(/档案已合并/)).toBeInTheDocument()
    expect(mergePayload).toEqual({
      target_candidate_id: 'candidate-2',
      reason: '人工核对电话和工作经历后确认是同一人',
    })
    await waitFor(() => {
      expect(screen.getByText('当前没有重复候选人提示')).toBeInTheDocument()
    })
  })

  it('人工排除重复提示并保留核对原因', async () => {
    let pendingReviews = [review]
    let dismissPayload: Record<string, unknown> | undefined
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      const base = baseResponse(path)
      if (base) return base
      if (path === '/api/candidates/duplicate-reviews?status=pending' && method === 'GET') {
        return jsonResponse(pendingReviews)
      }
      if (
        path === '/api/candidates/duplicate-reviews/review-1/dismiss' &&
        method === 'POST'
      ) {
        dismissPayload = JSON.parse(init?.body as string) as Record<string, unknown>
        pendingReviews = []
        return jsonResponse({
          ...review,
          status: 'not_duplicate',
          resolution_note: dismissPayload.reason,
          resolved_at: timestamp,
        })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderCandidateCenter(fetchMock)

    fireEvent.click(await screen.findByRole('tab', { name: '重复确认' }))
    fireEvent.click(await screen.findByRole('button', { name: /不是同一人/ }))
    fireEvent.change(screen.getByRole('textbox', { name: '处理原因' }), {
      target: { value: '号码为家庭共用，履历核对后确认不同人' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认排除' }))

    expect(await screen.findByText('已判定为不同候选人')).toBeInTheDocument()
    expect(dismissPayload).toEqual({ reason: '号码为家庭共用，履历核对后确认不同人' })
  })

  it('修正候选人手机号并提示撤回的门户链接数量', async () => {
    let currentDetail = candidateDetail
    let updatePayload: Record<string, unknown> | undefined
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(recruiter)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs?include_archived=true') return jsonResponse([])
      if (path.startsWith('/api/candidates?')) {
        return jsonResponse({
          items: [currentDetail, sourceCandidate],
          total: 2,
          limit: 20,
          offset: 0,
        })
      }
      if (path === '/api/candidates/candidate-1' && method === 'GET') {
        return jsonResponse(currentDetail)
      }
      if (path === '/api/candidates/candidate-1/phone' && method === 'PATCH') {
        updatePayload = JSON.parse(init?.body as string) as Record<string, unknown>
        currentDetail = { ...currentDetail, phone: '13999995678' }
        return jsonResponse({
          candidate_id: 'candidate-1',
          phone: '13999995678',
          revoked_portal_link_count: 2,
        })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderCandidateCenter(fetchMock)

    fireEvent.click((await screen.findAllByRole('button', { name: /查看/ }))[0])
    fireEvent.click(await screen.findByRole('button', { name: /修正手机号/ }))
    fireEvent.change(screen.getByRole('textbox', { name: '手机号' }), {
      target: { value: '13999995678' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: '修改原因' }), {
      target: { value: '候选人确认原号码录入错误' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认修改' }))

    expect(
      await screen.findByText('手机号已更新，已撤回 2 条旧门户链接'),
    ).toBeInTheDocument()
    expect(updatePayload).toEqual({
      phone: '13999995678',
      reason: '候选人确认原号码录入错误',
    })
    await waitFor(() => {
      expect(screen.getAllByText('13999995678').length).toBeGreaterThan(0)
    })
  })

  it('批量选择候选人并加入指定人才分组', async () => {
    let membershipPayload: Record<string, unknown> | undefined
    const talentGroup = {
      id: '11111111-1111-4111-8111-111111111111',
      name: '后端人才',
      description: null,
      version: 3,
      is_archived: false,
      member_count: 0,
      created_by_id: recruiter.id,
      created_by_display_name: recruiter.display_name,
      archived_at: null,
      archived_by_id: null,
      archived_by_display_name: null,
      created_at: timestamp,
      updated_at: timestamp,
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      const base = baseResponse(path)
      if (base) return base
      if (path === '/api/talent-pool/groups?status=active&limit=100') {
        return jsonResponse({ items: [talentGroup], total: 1, limit: 100, offset: 0 })
      }
      if (
        path === `/api/talent-pool/groups/${talentGroup.id}/memberships` &&
        method === 'POST'
      ) {
        membershipPayload = JSON.parse(init?.body as string) as Record<string, unknown>
        return jsonResponse({
          group_id: talentGroup.id,
          group_version: 4,
          items: [
            {
              requested_candidate_id: targetCandidate.id,
              candidate_id: targetCandidate.id,
              membership_id: '55555555-5555-4555-8555-555555555555',
              status: 'added',
            },
            {
              requested_candidate_id: sourceCandidate.id,
              candidate_id: sourceCandidate.id,
              membership_id: '66666666-6666-4666-8666-666666666666',
              status: 'added',
            },
          ],
        })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderCandidateCenter(fetchMock)

    await screen.findByText('张三')
    const checkboxes = screen.getAllByRole('checkbox')
    fireEvent.click(checkboxes[1])
    fireEvent.click(checkboxes[2])
    fireEvent.click(screen.getByRole('button', { name: /加入人才库 \(2\)/ }))
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '人才分组' }))
    fireEvent.click(await screen.findByText('后端人才（0 人）'))
    fireEvent.change(screen.getByRole('textbox', { name: '入库原因' }), {
      target: { value: '具备平台开发经验，适合持续关注' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认加入' }))

    expect(await screen.findByText('已将 2 位候选人加入人才库')).toBeInTheDocument()
    expect(membershipPayload).toMatchObject({
      members: [
        { candidate_id: targetCandidate.id },
        { candidate_id: sourceCandidate.id },
      ],
      reason: '具备平台开发经验，适合持续关注',
      expected_group_version: 3,
    })
    expect(membershipPayload?.idempotency_key).toEqual(expect.any(String))
  })

  it('从候选人详情发起单人入库', async () => {
    const talentGroup = {
      id: '11111111-1111-4111-8111-111111111111',
      name: '重点关注',
      description: null,
      version: 1,
      is_archived: false,
      member_count: 1,
      created_by_id: recruiter.id,
      created_by_display_name: recruiter.display_name,
      archived_at: null,
      archived_by_id: null,
      archived_by_display_name: null,
      created_at: timestamp,
      updated_at: timestamp,
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      const base = baseResponse(path)
      if (base) return base
      if (path === '/api/talent-pool/groups?status=active&limit=100') {
        return jsonResponse({ items: [talentGroup], total: 1, limit: 100, offset: 0 })
      }
      if (
        path === `/api/talent-pool/groups/${talentGroup.id}/memberships` &&
        method === 'POST'
      ) {
        return jsonResponse({
          group_id: talentGroup.id,
          group_version: 2,
          items: [
            {
              requested_candidate_id: targetCandidate.id,
              candidate_id: targetCandidate.id,
              membership_id: '55555555-5555-4555-8555-555555555555',
              status: 'already_active',
            },
          ],
        })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    renderCandidateCenter(fetchMock)

    fireEvent.click((await screen.findAllByRole('button', { name: /查看/ }))[0])
    await screen.findByText('张三 · CAND-000000000001')
    const addButton = screen.getAllByRole('button', { name: /加入人才库/ }).find(
      (button) => !button.hasAttribute('disabled'),
    )
    expect(addButton).toBeDefined()
    fireEvent.click(addButton!)
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '人才分组' }))
    fireEvent.click(await screen.findByText('重点关注（1 人）'))
    fireEvent.change(screen.getByRole('textbox', { name: '入库原因' }), {
      target: { value: '更新人才归档原因' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认加入' }))

    expect(await screen.findByText('已将 0 位候选人加入人才库，1 位已在该分组')).toBeInTheDocument()
  })
})
