import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type {
  CandidateComparison,
  RecruiterDecisionRecord,
  ScreeningResultDetail,
  ScreeningResultSummary,
} from './api/client'

const timestamp = '2026-07-23T03:00:00Z'
const user = {
  id: 'user-1',
  username: 'recruiter',
  display_name: '招聘专员',
  is_active: true,
  must_change_password: false,
  roles: ['recruiter'],
}
const job = {
  id: 'job-1',
  recruiter_id: user.id,
  hiring_manager_id: null,
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

function summary(
  id: string,
  candidateCode: string,
  score: number,
  criteriaVersionId = 'criteria-1',
  analysisVersion = 1,
): ScreeningResultSummary {
  return {
    id,
    batch_id: 'batch-1',
    batch_name: '候选人对比批次',
    document_id: `document-${id}`,
    candidate_code: candidateCode,
    criteria_version_id: criteriaVersionId,
    criteria_version_number: criteriaVersionId === 'criteria-1' ? 1 : 2,
    analysis_version: analysisVersion,
    status: 'completed',
    ai_group: score >= 60 ? 'passed' : 'low_match',
    total_score: score,
    pass_threshold: 60,
    current_decision: 'unprocessed',
    latest_decision_at: null,
    created_at: timestamp,
  }
}

function candidate(
  id: string,
  candidateCode: string,
  score: number,
): ScreeningResultDetail {
  return {
    id,
    document_id: `document-${id}`,
    candidate_code: candidateCode,
    criteria_version_id: 'criteria-1',
    criteria_version_number: 1,
    analysis_version: 1,
    status: 'completed',
    ai_group: score >= 60 ? 'passed' : 'low_match',
    total_score: score,
    pass_threshold: 60,
    hard_requirements: [
      {
        requirement_id: 'requirement-1',
        requirement_type: 'min_experience_years',
        title: '至少 3 年经验',
        expected_value: '3',
        auto_reject: true,
        status: 'passed',
        rationale: `${candidateCode} 满足经验要求。`,
        evidence_segment_keys: ['SEG-0001'],
      },
    ],
    strengths: [`${candidateCode} 的工程能力`],
    gaps: [`${candidateCode} 的团队经验待确认`],
    missing_items: ['值班经验'],
    interview_questions: [],
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
        id: `score-${id}`,
        scoring_dimension_id: 'dimension-1',
        dimension_name: '工程能力',
        score,
        weight_percent: 100,
        weighted_score: score,
        rationale: `${candidateCode} 的工程实践说明。`,
        missing_items: [],
        sort_order: 0,
        evidence: [
          {
            id: `citation-${id}`,
            subject_type: 'dimension',
            subject_key: 'dimension-1',
            segment_key: 'SEG-0001',
            quote: '平台工程经验',
            source_type: 'pdf_page',
            page_number: 1,
            paragraph_index: null,
            sort_order: 0,
          },
        ],
      },
    ],
    evidence: [],
    current_decision: 'unprocessed',
    decision_history: [],
  }
}

describe('candidate comparison flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('限制同版本选择并支持对比页直接作出人工结论', async () => {
    const summaries = [
      summary('result-1', 'CAND-0001', 88),
      summary('result-2', 'CAND-0002', 72),
      summary('result-3', 'CAND-0003', 91, 'criteria-2', 2),
      summary('result-4', 'CAND-0004', 79),
      summary('result-5', 'CAND-0005', 68),
    ]
    let candidates = [
      candidate('result-1', 'CAND-0001', 88),
      candidate('result-2', 'CAND-0002', 72),
      candidate('result-4', 'CAND-0004', 79),
    ]
    const compareBodies: string[][] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/screening-results' && method === 'GET') {
        return jsonResponse(summaries)
      }
      if (
        path === '/api/jobs/job-1/screening-results/compare' &&
        method === 'POST'
      ) {
        const payload = JSON.parse(init?.body as string) as { result_ids: string[] }
        compareBodies.push(payload.result_ids)
        const response: CandidateComparison = {
          job_id: 'job-1',
          criteria_version_id: 'criteria-1',
          criteria_version_number: 1,
          analysis_version: 1,
          candidates: payload.result_ids.map((id) => candidates.find((item) => item.id === id)!),
        }
        return jsonResponse(response)
      }
      if (
        path === '/api/jobs/job-1/screening-results/result-1/decisions' &&
        method === 'POST'
      ) {
        const decision: RecruiterDecisionRecord = {
          id: 'decision-1',
          screening_result_id: 'result-1',
          sequence_number: 1,
          previous_decision: 'unprocessed',
          decision: 'shortlisted',
          reason: '对比后工程能力更符合岗位',
          is_auto_rejection_override: false,
          operator_id: user.id,
          operator_display_name: user.display_name,
          created_at: timestamp,
        }
        candidates = candidates.map((item) =>
          item.id === 'result-1'
            ? { ...item, current_decision: 'shortlisted', decision_history: [decision] }
            : item,
        )
        return jsonResponse(decision, 201)
      }
      if (
        path === '/api/jobs/job-1/screening-results/result-1/evidence/citation-result-1'
      ) {
        return jsonResponse({
          citation_id: 'citation-result-1',
          segment_key: 'SEG-0001',
          quote: '平台工程经验',
          original_text: '候选人拥有稳定的平台工程经验。',
          source_type: 'pdf_page',
          page_number: 1,
          paragraph_index: null,
        })
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

    const firstRow = await screen.findByRole('row', { name: /CAND-0001/ })
    const secondRow = screen.getByRole('row', { name: /CAND-0002/ })
    const thirdRow = screen.getByRole('row', { name: /CAND-0003/ })
    const fourthRow = screen.getByRole('row', { name: /CAND-0004/ })
    const fifthRow = screen.getByRole('row', { name: /CAND-0005/ })
    fireEvent.click(within(firstRow).getByRole('checkbox'))
    fireEvent.click(within(secondRow).getByRole('checkbox'))

    expect(within(thirdRow).getByRole('checkbox')).toBeDisabled()
    fireEvent.click(within(fourthRow).getByRole('checkbox'))
    expect(within(fifthRow).getByRole('checkbox')).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: /对比候选人（3\/3）/ }))

    expect(await screen.findByRole('heading', { name: '候选人横向对比' })).toBeInTheDocument()
    expect(await screen.findByText('评分 · 工程能力')).toBeInTheDocument()
    expect(await screen.findByText('硬条件 · 至少 3 年经验')).toBeInTheDocument()
    expect(compareBodies[0]).toEqual(['result-1', 'result-2', 'result-4'])

    fireEvent.click(screen.getAllByRole('button', { name: /SEG-0001 · PDF 第 1 页/ })[0])
    expect(await screen.findByText('候选人拥有稳定的平台工程经验。')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Close' }).at(-1)!)

    fireEvent.click(screen.getAllByRole('button', { name: /入选/ })[0])
    fireEvent.change(screen.getByLabelText('决策原因（选填）'), {
      target: { value: '对比后工程能力更符合岗位' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存结论' }))

    expect(await screen.findByText('人工结论已保存')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getAllByText('入选').length).toBeGreaterThan(0)
      expect(compareBodies.length).toBeGreaterThan(1)
    })
  })
})
