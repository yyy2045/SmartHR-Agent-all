import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type {
  CandidateProcessCardRecord,
  InterviewEvaluationContext,
  InterviewEvaluationDraftInput,
  JobDetail,
} from './api/client'

const timestamp = '2026-07-26T12:00:00Z'
const evaluationPath =
  '/api/jobs/job-1/candidate-processes/document-1/interview-schedule/rounds/round-1/evaluation'

const user = {
  id: 'user-1',
  username: 'recruiter',
  display_name: '招聘专员',
  is_active: true,
  must_change_password: false,
  roles: ['recruiter'],
}

const job: JobDetail = {
  id: 'job-1',
  recruiter_id: user.id,
  hiring_manager_id: null,
  title: '高级后端工程师',
  department: '研发中心',
  original_jd: '负责核心服务设计与开发。',
  status: 'active',
  archived_at: null,
  created_at: timestamp,
  updated_at: timestamp,
  criteria_versions: [],
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

const baseContext: InterviewEvaluationContext = {
  round_id: 'round-1',
  plan_round_id: 'plan-round-1',
  round_name: '技术一面',
  round_type: 'technical',
  round_status: 'scheduled',
  pass_threshold: 70,
  scheduled_start_at: timestamp,
  questions: [
    {
      id: 'question-1',
      question_text: '请介绍一个高并发系统设计案例',
      evaluation_guide: '关注容量估算和架构取舍',
      sort_order: 0,
    },
    {
      id: 'question-2',
      question_text: '请说明一次线上故障复盘',
      evaluation_guide: '关注定位过程和改进措施',
      sort_order: 1,
    },
  ],
  dimensions: [
    {
      id: 'dimension-1',
      name: '系统设计',
      description: '架构设计与权衡能力',
      weight_percent: 60,
      sort_order: 0,
      anchors: [1, 2, 3, 4, 5].map((score) => ({
        score_value: score,
        description: `系统设计 ${score} 分标准`,
      })),
    },
    {
      id: 'dimension-2',
      name: '问题解决',
      description: '分析和解决复杂问题的能力',
      weight_percent: 40,
      sort_order: 1,
      anchors: [1, 2, 3, 4, 5].map((score) => ({
        score_value: score,
        description: `问题解决 ${score} 分标准`,
      })),
    },
  ],
  evaluation: null,
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function draftContext(payload: InterviewEvaluationDraftInput): InterviewEvaluationContext {
  return {
    ...baseContext,
    evaluation: {
      id: 'evaluation-1',
      status: 'draft',
      overall_recommendation: payload.overall_recommendation,
      overall_comment: payload.overall_comment,
      total_score: null,
      passed: null,
      submitted_by_id: null,
      submitted_at: null,
      created_at: timestamp,
      updated_at: timestamp,
      question_responses: payload.question_responses.map((item, index) => ({
        id: `response-${index + 1}`,
        ...item,
      })),
      dimension_ratings: payload.dimension_ratings.map((item, index) => ({
        id: `rating-${index + 1}`,
        ...item,
      })),
    },
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

describe('interview evaluation flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('保存不完整草稿并在完整填写后提交锁定', async () => {
    let context = baseContext
    const savedPayloads: InterviewEvaluationDraftInput[] = []
    let submitCount = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/candidate-processes') return jsonResponse([candidate])
      if (path === evaluationPath && method === 'GET') return jsonResponse(context)
      if (path === evaluationPath && method === 'PUT') {
        const payload = JSON.parse(init?.body as string) as InterviewEvaluationDraftInput
        savedPayloads.push(payload)
        context = draftContext(payload)
        return jsonResponse(context)
      }
      if (path === `${evaluationPath}/submit` && method === 'POST') {
        submitCount += 1
        context = {
          ...context,
          evaluation: {
            ...context.evaluation!,
            status: 'submitted',
            total_score: 72,
            passed: true,
            submitted_by_id: user.id,
            submitted_at: timestamp,
          },
        }
        return jsonResponse(context)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState(
      {},
      '',
      '/jobs/job-1/candidates/document-1/interview-evaluations/round-1',
    )
    renderApp()

    expect(await screen.findByRole('heading', { name: 'CAND-0001' })).toBeInTheDocument()
    expect(screen.getByText('技术一面')).toBeInTheDocument()
    expect(screen.queryByText(/系统设计 4 分标准/)).not.toBeInTheDocument()

    fireEvent.change(
      screen.getByLabelText('回答摘要：请介绍一个高并发系统设计案例'),
      { target: { value: '设计了分层缓存和异步削峰方案。' } },
    )
    fireEvent.change(
      screen.getByLabelText('事实证据：请介绍一个高并发系统设计案例'),
      { target: { value: '给出了十万 QPS 的容量估算。' } },
    )
    fireEvent.click(screen.getByRole('button', { name: /保存草稿/ }))

    expect(await screen.findByText('面试评价草稿已保存')).toBeInTheDocument()
    expect(savedPayloads).toHaveLength(1)
    expect(savedPayloads[0].question_responses[0].answer_summary).toContain('分层缓存')
    expect(savedPayloads[0].question_responses[1].answer_summary).toBe('')

    fireEvent.change(screen.getByLabelText('回答摘要：请说明一次线上故障复盘'), {
      target: { value: '通过指标和链路追踪定位连接池耗尽。' },
    })
    fireEvent.change(screen.getByLabelText('事实证据：请说明一次线上故障复盘'), {
      target: { value: '说明了告警阈值和压测门禁。' },
    })
    fireEvent.click(screen.getByRole('radio', { name: '系统设计 4 分' }))
    fireEvent.change(screen.getByLabelText('评分依据：系统设计'), {
      target: { value: '架构分层清晰，能够解释一致性与性能取舍。' },
    })
    fireEvent.click(screen.getByRole('radio', { name: '问题解决 3 分' }))
    fireEvent.change(screen.getByLabelText('评分依据：问题解决'), {
      target: { value: '定位过程完整，但风险预案深度一般。' },
    })
    fireEvent.click(screen.getByRole('radio', { name: '推荐' }))
    fireEvent.change(screen.getByLabelText('总体评语'), {
      target: { value: '技术基础扎实，建议进入下一轮。' },
    })
    expect(screen.getByText(/4 分锚点：系统设计 4 分标准/)).toBeInTheDocument()
    expect(screen.getByText('当前建议：推荐')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /正式提交并锁定/ }))
    fireEvent.click(await screen.findByRole('button', { name: /确认提交/ }))

    expect(await screen.findByText('面试评价已提交并锁定')).toBeInTheDocument()
    expect(screen.getByText('评价已正式提交并锁定')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '通过' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /保存草稿/ })).not.toBeInTheDocument()
    expect(submitCount).toBe(1)
    expect(savedPayloads).toHaveLength(2)
    expect(savedPayloads[1].dimension_ratings.map((item) => item.score)).toEqual([4, 3])
    await waitFor(() =>
      expect(
        screen.getByLabelText('回答摘要：请介绍一个高并发系统设计案例'),
      ).toBeDisabled(),
    )
  })
})
