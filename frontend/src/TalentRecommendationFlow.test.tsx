import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type {
  AuthUser,
  JobDetail,
  JobRecord,
  TalentPoolGroupRecord,
  TalentRecommendationResultRecord,
  TalentRecommendationRunDetailRecord,
  TalentRecommendationRunRecord,
} from './api/client'

const timestamp = '2026-07-30T08:00:00Z'
const jobId = '11111111-1111-4111-8111-111111111111'
const runId = '22222222-2222-4222-8222-222222222222'
const groupId = '33333333-3333-4333-8333-333333333333'
const resultId = '44444444-4444-4444-8444-444444444444'
const applicationId = '55555555-5555-4555-8555-555555555555'

const job: JobRecord = {
  id: jobId,
  title: '高级后端工程师',
  department: '研发中心',
  original_jd: '负责企业系统研发',
  recruiter_id: '66666666-6666-4666-8666-666666666666',
  hiring_manager_id: '77777777-7777-4777-8777-777777777777',
  recruitment_request_id: null,
  status: 'active',
  archived_at: null,
  created_at: timestamp,
  updated_at: timestamp,
}

const jobDetail: JobDetail = {
  ...job,
  criteria_versions: [
    {
      id: '88888888-8888-4888-8888-888888888888',
      job_id: jobId,
      version_number: 3,
      status: 'confirmed',
      pass_threshold: 70,
      source_version_id: null,
      confirmed_by_id: job.recruiter_id,
      confirmed_at: timestamp,
      created_at: timestamp,
      updated_at: timestamp,
      hard_requirements: [],
      scoring_dimensions: [],
    },
  ],
}

const group: TalentPoolGroupRecord = {
  id: groupId,
  name: '后端人才',
  description: '平台研发候选人',
  version: 1,
  is_archived: false,
  member_count: 8,
  created_by_id: job.recruiter_id,
  created_by_display_name: '招聘专员',
  archived_at: null,
  archived_by_id: null,
  archived_by_display_name: null,
  created_at: timestamp,
  updated_at: timestamp,
}

const run: TalentRecommendationRunRecord = {
  id: runId,
  job_id: jobId,
  job_title: job.title,
  criteria_version_id: jobDetail.criteria_versions[0].id,
  criteria_version_number: 3,
  created_by_id: job.recruiter_id,
  created_by_username: 'recruiter',
  created_by_display_name: '招聘专员',
  status: 'completed',
  ai_input_mode: 'raw',
  recall_limit: 50,
  rescore_limit: 20,
  scope_candidate_count: 8,
  retrieved_count: 1,
  rescored_count: 1,
  completed_count: 1,
  failed_count: 0,
  excluded_count: 0,
  criteria_stale: false,
  criteria_stale_at: null,
  failure_code: null,
  failure_summary: null,
  resource_version: 2,
  started_at: timestamp,
  completed_at: timestamp,
  created_at: timestamp,
  updated_at: timestamp,
  groups: [{ group_id: groupId, group_name: group.name, group_version: 1 }],
  allowed_actions: ['select_candidates'],
}

const result: TalentRecommendationResultRecord = {
  id: resultId,
  candidate_id: '99999999-9999-4999-8999-999999999999',
  resolved_candidate_id: '99999999-9999-4999-8999-999999999999',
  candidate_code: 'CAND-000000000001',
  candidate_name: '张三',
  candidate_merged_at: null,
  document_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  candidate_profile_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  profile_version: 2,
  vector_rank: 1,
  similarity_score: 0.91,
  matched_group_ids: [groupId],
  matched_chunks: [{ quote: '具备五年 Python 企业系统经验。' }],
  status: 'completed',
  ai_score: 88,
  ai_group: 'passed',
  ai_dimension_scores: [{ name: '技术能力', score: 88, rationale: '经验匹配' }],
  ai_hard_requirement_results: [
    { title: '工作经验', status: 'passed', rationale: '满足五年要求' },
  ],
  ai_strengths: ['企业系统经验'],
  ai_gaps: ['云平台经验待确认'],
  ai_missing_items: [],
  ai_interview_questions: [],
  ai_evidence: [{ quote: '具备五年 Python 企业系统经验。', page_number: 1 }],
  processing_attempt_count: 1,
  failure_code: null,
  failure_message: null,
  exclusion_code: null,
  exclusion_reason: null,
  document_stale: false,
  profile_stale: false,
  embedding_stale: false,
  stale_at: null,
  completed_at: timestamp,
}

const detail: TalentRecommendationRunDetailRecord = { ...run, results: [result] }

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function user(roles: AuthUser['roles']): AuthUser {
  return {
    id: job.recruiter_id,
    username: roles[0],
    display_name: '测试用户',
    is_active: true,
    must_change_password: false,
    roles,
  }
}

function renderPage(
  authUser: AuthUser,
  path: string,
  onRequest?: (path: string, init?: RequestInit) => Response | undefined,
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const requestPath = input.toString()
    if (requestPath === '/api/auth/me') return jsonResponse(authUser)
    if (requestPath === '/api/health/live') return jsonResponse({ status: 'ok' })
    const custom = onRequest?.(requestPath, init)
    if (custom) return custom
    if (requestPath === '/api/jobs?include_archived=true') return jsonResponse([job])
    if (requestPath === `/api/jobs/${jobId}`) return jsonResponse(jobDetail)
    if (requestPath.startsWith('/api/talent-pool/groups?')) {
      return jsonResponse({ items: [group], total: 1, limit: 100, offset: 0 })
    }
    if (requestPath.startsWith(`/api/jobs/${jobId}/recommendations?`)) {
      return jsonResponse({ items: [run], total: 1, limit: 20, offset: 0 })
    }
    if (requestPath === `/api/jobs/${jobId}/recommendations/${runId}`) {
      return jsonResponse(detail)
    }
    return jsonResponse({ detail: 'not found' }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  window.history.replaceState({}, '', path)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
  return fetchMock
}

function modalPrimaryButton() {
  const dialog = screen.getByRole('dialog')
  const button = dialog.querySelector<HTMLButtonElement>('.ant-modal-footer .ant-btn-primary')
  expect(button).not.toBeNull()
  return button!
}

describe('talent recommendation flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('招聘专员从职位深链创建默认原文推荐并复用运行中任务', async () => {
    let createBody: Record<string, unknown> | undefined
    const fetchMock = renderPage(
      user(['recruiter']),
      `/talent?view=recommendations&job_id=${jobId}&create=1`,
      (path, init) => {
        if (path === `/api/jobs/${jobId}/recommendations` && init?.method === 'POST') {
          createBody = JSON.parse(init.body as string) as Record<string, unknown>
          return jsonResponse({ run, replayed: false, reused_active_run: true }, 202)
        }
        return undefined
      },
    )

    expect(await screen.findByRole('dialog', { name: '新建人才推荐任务' })).toBeInTheDocument()
    expect(await screen.findByText('已确认 V3')).toBeInTheDocument()
    expect(screen.getByText(/最多召回 50 人/)).toBeInTheDocument()
    await waitFor(() => expect(modalPrimaryButton()).toBeEnabled())
    fireEvent.click(modalPrimaryButton())

    expect(await screen.findByText('已打开正在执行的推荐任务')).toBeInTheDocument()
    expect(createBody).toMatchObject({
      group_ids: [groupId],
      ai_input_mode: 'raw',
      idempotency_key: expect.any(String),
    })
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input]) => input.toString() === `/api/jobs/${jobId}/recommendations/${runId}`,
        ),
      ).toBe(true),
    )
  })

  it('职位详情标题区可以直接进入人才推荐创建', async () => {
    renderPage(user(['recruiter']), `/jobs/${jobId}/edit`, (path) => {
      if (path === '/api/users/options?role=hiring_manager') return jsonResponse([])
      return undefined
    })

    fireEvent.click(await screen.findByRole('button', { name: /从人才库推荐/ }))
    expect(await screen.findByRole('dialog', { name: '新建人才推荐任务' })).toBeInTheDocument()
    expect(await screen.findByText('已确认 V3')).toBeInTheDocument()
  })

  it('只重试主简历变化项并在确认后使用锁定旧简历转应聘', async () => {
    const selectBodies: Array<Record<string, unknown>> = []
    renderPage(
      user(['recruiter']),
      `/talent?view=recommendations&job_id=${jobId}&run_id=${runId}`,
      (path, init) => {
        if (
          path === `/api/jobs/${jobId}/recommendations/${runId}/select` &&
          init?.method === 'POST'
        ) {
          const body = JSON.parse(init.body as string) as Record<string, unknown>
          selectBodies.push(body)
          return selectBodies.length === 1
            ? jsonResponse({
                created_count: 0,
                existing_count: 0,
                failed_count: 1,
                items: [
                  {
                    result_id: resultId,
                    status: 'failed',
                    application_id: null,
                    screening_result_id: null,
                    failure_code: 'primary_document_changed',
                    failure_message: '当前主简历已变化',
                  },
                ],
              })
            : jsonResponse({
                created_count: 1,
                existing_count: 0,
                failed_count: 0,
                items: [
                  {
                    result_id: resultId,
                    status: 'created',
                    application_id: applicationId,
                    screening_result_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
                    failure_code: null,
                    failure_message: null,
                  },
                ],
              })
        }
        return undefined
      },
    )

    expect(await screen.findByText('张三')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: '选择 张三' }))
    fireEvent.click(screen.getByRole('button', { name: /转为应聘（1\/20）/ }))
    fireEvent.click(await screen.findByRole('button', { name: '确认创建应聘' }))
    fireEvent.click(await screen.findByRole('button', { name: '确认使用旧简历' }))

    expect(await screen.findByText('已创建 1 条应聘，0 条已存在，0 条失败')).toBeInTheDocument()
    expect(selectBodies).toHaveLength(2)
    expect(selectBodies[0]).toMatchObject({
      result_ids: [resultId],
      confirmed_stale_result_ids: [],
    })
    expect(selectBodies[1]).toMatchObject({
      result_ids: [resultId],
      confirmed_stale_result_ids: [resultId],
    })
    expect(selectBodies[1].idempotency_key).not.toBe(selectBodies[0].idempotency_key)
    expect(await screen.findByRole('button', { name: '查看候选人流程' })).toBeInTheDocument()
  })

  it('部分完成任务可以重试失败项', async () => {
    const partialRun = {
      ...run,
      status: 'partial' as const,
      failed_count: 1,
      allowed_actions: ['retry_failed_items', 'select_candidates'] as const,
    }
    const partialDetail = { ...detail, ...partialRun }
    let retried = false
    renderPage(
      user(['administrator']),
      `/talent?view=recommendations&job_id=${jobId}&run_id=${runId}`,
      (path, init) => {
        if (path.startsWith(`/api/jobs/${jobId}/recommendations?`)) {
          return jsonResponse({ items: [partialRun], total: 1, limit: 20, offset: 0 })
        }
        if (path === `/api/jobs/${jobId}/recommendations/${runId}`) {
          return jsonResponse(partialDetail)
        }
        if (
          path === `/api/jobs/${jobId}/recommendations/${runId}/retry-failures` &&
          init?.method === 'POST'
        ) {
          retried = true
          return jsonResponse({ ...partialRun, status: 'rescoring', resource_version: 3 })
        }
        return undefined
      },
    )

    expect((await screen.findAllByText('部分完成')).length).toBeGreaterThan(0)
    fireEvent.click(await screen.findByRole('button', { name: /重试失败项/ }))
    expect(await screen.findByText('失败项已重新入队')).toBeInTheDocument()
    expect(retried).toBe(true)
  })

  it('用人经理只有查看权限且无效任务深链可以退出', async () => {
    renderPage(
      user(['hiring_manager']),
      `/talent?view=recommendations&job_id=${jobId}&run_id=dddddddd-dddd-4ddd-8ddd-dddddddddddd`,
      (path) => {
        if (path.endsWith('/dddddddd-dddd-4ddd-8ddd-dddddddddddd')) {
          return jsonResponse({ detail: '推荐任务不存在' }, 404)
        }
        return undefined
      },
    )

    expect(await screen.findByText('推荐任务详情读取失败')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '新建推荐任务' })).not.toBeInTheDocument()
    const drawer = screen.getByRole('dialog')
    fireEvent.click(within(drawer).getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByText('推荐任务详情读取失败')).not.toBeInTheDocument())
  })
})
