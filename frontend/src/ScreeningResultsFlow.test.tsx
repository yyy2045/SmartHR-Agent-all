import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type {
  RecruiterDecisionRecord,
  ScreeningResultDetail,
  ScreeningResultSummary,
} from './api/client'

const timestamp = '2026-07-23T02:00:00Z'
const user = {
  id: 'user-1',
  username: 'recruiter',
  display_name: '招聘专员',
}
const job = {
  id: 'job-1',
  title: '平台工程师',
  department: '研发中心',
  original_jd: '负责平台工程建设。',
  status: 'active' as const,
  archived_at: null,
  created_at: timestamp,
  updated_at: timestamp,
  criteria_versions: [],
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function makeSummary(
  overrides: Partial<ScreeningResultSummary> = {},
): ScreeningResultSummary {
  return {
    id: 'result-1',
    batch_id: 'batch-1',
    batch_name: '校招第一批',
    document_id: 'document-1',
    candidate_code: 'CAND-0001',
    criteria_version_id: 'criteria-1',
    criteria_version_number: 1,
    analysis_version: 1,
    status: 'completed',
    ai_group: 'passed',
    total_score: 88,
    pass_threshold: 60,
    current_decision: 'unprocessed',
    latest_decision_at: null,
    created_at: timestamp,
    ...overrides,
  }
}

function makeDetail(
  overrides: Partial<ScreeningResultDetail> = {},
): ScreeningResultDetail {
  return {
    id: 'result-1',
    document_id: 'document-1',
    candidate_code: 'CAND-0001',
    criteria_version_id: 'criteria-1',
    criteria_version_number: 1,
    analysis_version: 1,
    status: 'completed',
    ai_group: 'passed',
    total_score: 88,
    pass_threshold: 60,
    hard_requirements: [
      {
        requirement_id: 'requirement-1',
        requirement_type: 'min_experience_years',
        title: '至少 3 年经验',
        expected_value: '3',
        auto_reject: true,
        status: 'passed',
        rationale: '简历明确显示 5 年相关经验。',
        evidence_segment_keys: ['SEG-0001'],
      },
    ],
    strengths: ['Python 工程能力扎实'],
    gaps: ['大型团队协作信息较少'],
    missing_items: ['未说明值班经验'],
    interview_questions: ['请介绍一次复杂故障处理经历。'],
    model_name: 'stub-model',
    prompt_version: 'resume-match-v1',
    failure_code: null,
    failure_message: null,
    started_at: timestamp,
    completed_at: timestamp,
    created_at: timestamp,
    candidate_profile: null,
    dimension_scores: [
      {
        id: 'score-1',
        scoring_dimension_id: 'dimension-1',
        dimension_name: '工程能力',
        score: 88,
        weight_percent: 100,
        weighted_score: 88,
        rationale: '具备稳定的平台工程实践。',
        missing_items: [],
        sort_order: 0,
        evidence: [
          {
            id: 'citation-1',
            subject_type: 'dimension',
            subject_key: 'dimension-1',
            segment_key: 'SEG-0001',
            quote: 'Python 平台工程经验',
            source_type: 'pdf_page',
            page_number: 1,
            paragraph_index: null,
            sort_order: 0,
          },
        ],
      },
    ],
    evidence: [
      {
        id: 'citation-hard-1',
        subject_type: 'hard_requirement',
        subject_key: 'requirement-1',
        segment_key: 'SEG-0001',
        quote: '5 年平台工程经验',
        source_type: 'pdf_page',
        page_number: 1,
        paragraph_index: null,
        sort_order: 0,
      },
    ],
    current_decision: 'unprocessed',
    decision_history: [],
    ...overrides,
  }
}

describe('screening results and recruiter decisions', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('展示评分证据并保存独立的人工结论历史', async () => {
    let summary = makeSummary()
    let detail = makeDetail()
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/screening-results' && method === 'GET') {
        return jsonResponse([summary])
      }
      if (path === '/api/jobs/job-1/screening-results/result-1' && method === 'GET') {
        return jsonResponse(detail)
      }
      if (
        path ===
          '/api/jobs/job-1/screening-results/result-1/evidence/citation-1' &&
        method === 'GET'
      ) {
        return jsonResponse({
          citation_id: 'citation-1',
          segment_key: 'SEG-0001',
          quote: 'Python 平台工程经验',
          original_text: '张三拥有 5 年 Python 平台工程经验。',
          source_type: 'pdf_page',
          page_number: 1,
          paragraph_index: null,
        })
      }
      if (
        path === '/api/jobs/job-1/screening-results/result-1/decisions' &&
        method === 'POST'
      ) {
        const payload = JSON.parse(init?.body as string) as {
          decision: 'shortlisted'
          reason: string
        }
        const decision: RecruiterDecisionRecord = {
          id: 'decision-1',
          screening_result_id: 'result-1',
          sequence_number: 1,
          previous_decision: 'unprocessed',
          decision: payload.decision,
          reason: payload.reason,
          is_auto_rejection_override: false,
          operator_id: user.id,
          operator_display_name: user.display_name,
          created_at: timestamp,
        }
        summary = { ...summary, current_decision: 'shortlisted', latest_decision_at: timestamp }
        detail = { ...detail, current_decision: 'shortlisted', decision_history: [decision] }
        return jsonResponse(decision, 201)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/jobs/job-1/results')
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: '平台工程师' })).toBeInTheDocument()
    expect(screen.getByText('CAND-0001')).toBeInTheDocument()
    expect(screen.getByText('88.0')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /查看依据/ }))

    expect(await screen.findByText('分维度评分')).toBeInTheDocument()
    expect(screen.getByText('Python 工程能力扎实')).toBeInTheDocument()
    expect(screen.getByText('请介绍一次复杂故障处理经历。')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /SEG-0001 · PDF 第 1 页/ }))
    expect(await screen.findByText('张三拥有 5 年 Python 平台工程经验。')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Close' }).at(-1)!)

    fireEvent.click(screen.getByRole('button', { name: /标记入选/ }))
    fireEvent.change(screen.getByLabelText('决策原因（选填）'), {
      target: { value: '技术能力符合当前岗位' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存结论' }))

    expect(await screen.findByText('人工结论已保存并记录变更历史')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getAllByText('入选').length).toBeGreaterThan(0)
      expect(screen.getByText('未处理 → 入选')).toBeInTheDocument()
    })
  })

  it('恢复自动淘汰时在前端强制填写原因', async () => {
    const summary = makeSummary({ ai_group: 'auto_rejected' })
    const detail = makeDetail({ ai_group: 'auto_rejected' })
    let decisionRequests = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/screening-results') return jsonResponse([summary])
      if (path === '/api/jobs/job-1/screening-results/result-1') return jsonResponse(detail)
      if (
        path === '/api/jobs/job-1/screening-results/result-1/decisions' &&
        method === 'POST'
      ) {
        decisionRequests += 1
        return jsonResponse({ detail: 'unused' }, 500)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/jobs/job-1/results')
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )

    fireEvent.click(await screen.findByRole('button', { name: /查看依据/ }))
    fireEvent.click(await screen.findByRole('button', { name: /标记待定/ }))
    expect(screen.getByText('该候选人由硬性条件自动淘汰，恢复时必须填写原因')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '保存结论' }))

    expect(await screen.findByText('恢复自动淘汰候选人时必须填写原因')).toBeInTheDocument()
    expect(decisionRequests).toBe(0)
  })
})
