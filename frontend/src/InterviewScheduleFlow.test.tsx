import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type {
  CandidateProcessCardRecord,
  InterviewPlanVersion,
  InterviewScheduleCreateInput,
  InterviewScheduleRecord,
  InterviewScheduleRoundRecord,
  JobDetail,
} from './api/client'

const timestamp = '2026-07-26T12:00:00Z'
const user = {
  id: 'user-1',
  username: 'recruiter',
  display_name: '招聘专员',
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function job(status: 'active' | 'archived' = 'active'): JobDetail {
  return {
    id: 'job-1',
    title: '高级后端工程师',
    department: '研发中心',
    original_jd: '负责核心服务设计与开发。',
    status,
    archived_at: status === 'archived' ? timestamp : null,
    created_at: timestamp,
    updated_at: timestamp,
    criteria_versions: [],
  }
}

const candidate: CandidateProcessCardRecord = {
  process_id: 'process-1',
  screening_result_id: 'result-1',
  batch_id: 'batch-1',
  batch_name: '社招批次',
  document_id: 'document-1',
  candidate_code: 'CAND-0001',
  original_filename: 'candidate.pdf',
  phone: null,
  ai_group: 'passed',
  total_score: 88,
  current_decision: 'shortlisted',
  current_stage: 'to_interview',
  stage_entered_at: timestamp,
  skills: ['Python'],
  analysis_created_at: timestamp,
}

const plan: InterviewPlanVersion = {
  id: 'plan-1',
  job_id: 'job-1',
  version_number: 1,
  status: 'confirmed',
  source_version_id: null,
  confirmed_by_id: user.id,
  confirmed_at: timestamp,
  created_at: timestamp,
  updated_at: timestamp,
  rounds: [
    {
      id: 'plan-round-1',
      name: '技术一面',
      round_type: 'technical',
      duration_minutes: 60,
      pass_threshold: 70,
      focus: '系统设计与工程质量',
      sort_order: 0,
      questions: [],
      scoring_dimensions: [],
    },
    {
      id: 'plan-round-2',
      name: 'HR 面',
      round_type: 'hr',
      duration_minutes: 30,
      pass_threshold: 60,
      focus: '发展意愿与价值观',
      sort_order: 1,
      questions: [],
      scoring_dimensions: [],
    },
  ],
}

function roundFromInput(
  input: InterviewScheduleCreateInput['rounds'][number],
  index: number,
): InterviewScheduleRoundRecord {
  const planRound = plan.rounds[index]
  return {
    id: `schedule-round-${index + 1}`,
    plan_round_id: input.plan_round_id,
    name: planRound.name,
    round_type: planRound.round_type,
    duration_minutes: planRound.duration_minutes,
    sort_order: index,
    scheduled_start_at: input.scheduled_start_at,
    interview_method: input.interview_method,
    location: input.location,
    meeting_url: input.meeting_url,
    status: 'scheduled',
    reschedule_count: 0,
    last_change_reason: null,
    updated_by_id: user.id,
    cancelled_at: null,
    created_at: timestamp,
    updated_at: timestamp,
  }
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

describe('candidate interview scheduling flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('按确认方案创建完整轮次并支持改期和取消', async () => {
    let schedule: InterviewScheduleRecord | null = null
    let createPayload: InterviewScheduleCreateInput | undefined
    let rescheduleReason: string | undefined
    let cancelReason: string | undefined
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job())
      if (path === '/api/jobs/job-1/candidate-processes') return jsonResponse([candidate])
      if (path === '/api/jobs/job-1/interview-plans/versions') return jsonResponse([plan])
      if (
        path === '/api/jobs/job-1/candidate-processes/document-1/interview-schedule' &&
        method === 'GET'
      ) {
        return schedule ? jsonResponse(schedule) : jsonResponse({ detail: '不存在' }, 404)
      }
      if (
        path === '/api/jobs/job-1/candidate-processes/document-1/interview-schedule' &&
        method === 'POST'
      ) {
        createPayload = JSON.parse(init?.body as string) as InterviewScheduleCreateInput
        schedule = {
          id: 'schedule-1',
          document_id: 'document-1',
          candidate_code: 'CAND-0001',
          plan_version_id: 'plan-1',
          plan_version_number: 1,
          status: 'scheduled',
          created_by_id: user.id,
          created_at: timestamp,
          updated_at: timestamp,
          rounds: createPayload.rounds.map(roundFromInput),
        }
        return jsonResponse(schedule, 201)
      }
      if (path.endsWith('/rounds/schedule-round-1') && method === 'PATCH' && schedule) {
        const payload = JSON.parse(init?.body as string) as {
          reason: string
          scheduled_start_at: string
          interview_method: 'onsite' | 'online' | 'phone'
          location: string | null
          meeting_url: string | null
        }
        rescheduleReason = payload.reason
        schedule = {
          ...schedule,
          rounds: schedule.rounds.map((round) =>
            round.id === 'schedule-round-1'
              ? {
                  ...round,
                  ...payload,
                  status: 'rescheduled',
                  reschedule_count: 1,
                  last_change_reason: payload.reason,
                }
              : round,
          ),
        }
        return jsonResponse(schedule)
      }
      if (path.endsWith('/rounds/schedule-round-1/cancel') && method === 'POST' && schedule) {
        const payload = JSON.parse(init?.body as string) as { reason: string }
        cancelReason = payload.reason
        schedule = {
          ...schedule,
          status: 'partially_cancelled',
          rounds: schedule.rounds.map((round) =>
            round.id === 'schedule-round-1'
              ? {
                  ...round,
                  status: 'cancelled',
                  last_change_reason: payload.reason,
                  cancelled_at: timestamp,
                }
              : round,
          ),
        }
        return jsonResponse(schedule)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState(
      {},
      '',
      '/jobs/job-1/candidates/document-1/interview-schedule',
    )
    renderApp()

    expect(await screen.findByRole('heading', { name: 'CAND-0001' })).toBeInTheDocument()
    expect(await screen.findByText('创建候选人面试安排')).toBeInTheDocument()
    expect(await screen.findByText(/技术一面/)).toBeInTheDocument()
    expect(screen.getByText(/HR 面/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /创建面试安排/ }))

    expect(await screen.findByText('候选人面试安排已创建')).toBeInTheDocument()
    expect(createPayload?.plan_version_id).toBe('plan-1')
    expect(createPayload?.rounds).toHaveLength(2)
    expect(createPayload?.rounds.map((item) => item.plan_round_id)).toEqual([
      'plan-round-1',
      'plan-round-2',
    ])
    expect(screen.getAllByRole('button', { name: /面试评价/ })).toHaveLength(2)

    fireEvent.click(screen.getAllByRole('button', { name: /改期/ })[0])
    fireEvent.change(screen.getByLabelText('改期原因'), {
      target: { value: '候选人临时出差' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认改期' }))
    expect(await screen.findByText('面试轮次已改期')).toBeInTheDocument()
    expect(rescheduleReason).toBe('候选人临时出差')
    expect(screen.getByText('最近改期原因')).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: /取消本轮/ })[0])
    fireEvent.change(screen.getByLabelText('取消原因'), {
      target: { value: '候选人退出本轮面试' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认取消本轮' }))
    expect(await screen.findByText('面试轮次已取消')).toBeInTheDocument()
    expect(cancelReason).toBe('候选人退出本轮面试')
    expect(screen.getByText('部分取消')).toBeInTheDocument()
    expect(screen.getByText('取消原因')).toBeInTheDocument()
  })

  it('归档职位只能查看已有安排', async () => {
    const schedule: InterviewScheduleRecord = {
      id: 'schedule-1',
      document_id: 'document-1',
      candidate_code: 'CAND-0001',
      plan_version_id: 'plan-1',
      plan_version_number: 1,
      status: 'scheduled',
      created_by_id: user.id,
      created_at: timestamp,
      updated_at: timestamp,
      rounds: [
        roundFromInput(
          {
            plan_round_id: 'plan-round-1',
            scheduled_start_at: timestamp,
            interview_method: 'onsite',
            location: '上海办公室',
            meeting_url: null,
          },
          0,
        ),
      ],
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job('archived'))
      if (path === '/api/jobs/job-1/candidate-processes') return jsonResponse([candidate])
      if (path === '/api/jobs/job-1/interview-plans/versions') return jsonResponse([plan])
      if (path.endsWith('/interview-schedule')) return jsonResponse(schedule)
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState(
      {},
      '',
      '/jobs/job-1/candidates/document-1/interview-schedule',
    )
    renderApp()

    expect(
      await screen.findByText('该职位已归档，候选人面试安排仅供查看'),
    ).toBeInTheDocument()
    expect(await screen.findByText('上海办公室')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /改期/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /取消本轮/ })).not.toBeInTheDocument()
  })
})
