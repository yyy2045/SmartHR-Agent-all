import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type {
  CandidateProcessCardRecord,
  CandidateProcessTimelineEventRecord,
} from './api/client'

const timestamp = '2026-07-26T02:00:00Z'
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

describe('candidate process board', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('按阶段展示候选人并保存人工流程变化与时间线', async () => {
    let candidate: CandidateProcessCardRecord = {
      process_id: null,
      screening_result_id: 'result-1',
      batch_id: 'batch-1',
      batch_name: '校招第一批',
      document_id: 'document-1',
      candidate_code: 'CAND-0001',
      original_filename: 'candidate.pdf',
      ai_group: 'passed',
      total_score: 88,
      current_decision: 'unprocessed',
      current_stage: 'unprocessed',
      stage_entered_at: timestamp,
      skills: ['Python', 'FastAPI', 'PostgreSQL', 'React', 'Docker'],
      analysis_created_at: timestamp,
    }
    let timeline: CandidateProcessTimelineEventRecord[] = []
    let stageRequest: Record<string, unknown> | undefined
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/batches') {
        return jsonResponse([{ id: 'batch-1', name: '校招第一批' }])
      }
      if (path.startsWith('/api/jobs/job-1/candidate-processes?') && method === 'GET') {
        return jsonResponse([candidate])
      }
      if (path === '/api/jobs/job-1/candidate-processes' && method === 'GET') {
        return jsonResponse([candidate])
      }
      if (
        path === '/api/jobs/job-1/candidate-processes/document-1/stage' &&
        method === 'POST'
      ) {
        stageRequest = JSON.parse(init?.body as string) as Record<string, unknown>
        candidate = {
          ...candidate,
          process_id: 'process-1',
          current_decision: 'pending',
          current_stage: 'pending',
          stage_entered_at: timestamp,
        }
        timeline = [
          {
            event_type: 'stage',
            from_stage: 'unprocessed',
            to_stage: 'pending',
            reason: null,
            operator_id: user.id,
            operator_display_name: user.display_name,
            created_at: timestamp,
          },
        ]
        return jsonResponse({
          process_id: 'process-1',
          document_id: 'document-1',
          previous_stage: 'unprocessed',
          current_stage: 'pending',
          stage_entered_at: timestamp,
        })
      }
      if (
        path === '/api/jobs/job-1/candidate-processes/document-1/timeline' &&
        method === 'GET'
      ) {
        return jsonResponse(timeline)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/jobs/job-1/pipeline')
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
    expect(screen.getByText('candidate.pdf')).toBeInTheDocument()
    expect(screen.getByText('Python')).toBeInTheDocument()
    expect(screen.getByText('+2')).toHaveAttribute('title', 'React、Docker')
    expect(screen.queryByText('React')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /调整阶段/ }))
    fireEvent.click(screen.getByRole('button', { name: '确认调整' }))

    expect(await screen.findByText('候选人阶段已更新')).toBeInTheDocument()
    expect(stageRequest).toEqual({
      expected_stage: 'unprocessed',
      target_stage: 'pending',
      reason: null,
    })
    await waitFor(() => {
      expect(screen.getByText('需要补充信息或进一步确认')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: '更多操作 CAND-0001' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: /查看时间线/ }))
    expect(await screen.findByText('待人工处理 → 待定')).toBeInTheDocument()
    expect(screen.getAllByText(/招聘专员/).length).toBeGreaterThan(0)
  })

  it('从候选人卡片进入对应档案页面', async () => {
    const candidate: CandidateProcessCardRecord = {
      process_id: null,
      screening_result_id: 'result-1',
      batch_id: 'batch-1',
      batch_name: '社招批次',
      document_id: 'document-1',
      candidate_code: 'CAND-0001',
      original_filename: 'candidate.pdf',
      ai_group: 'passed',
      total_score: 88,
      current_decision: 'shortlisted',
      current_stage: 'shortlisted',
      stage_entered_at: timestamp,
      skills: [],
      analysis_created_at: timestamp,
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/batches') return jsonResponse([])
      if (path === '/api/jobs/job-1/candidate-processes') return jsonResponse([candidate])
      if (path.endsWith('/profiles')) return jsonResponse([])
      if (path.endsWith('/analysis-history')) return jsonResponse([])
      if (path.includes('/documents/document-1') && !path.endsWith('/file')) {
        return jsonResponse({
          id: 'document-1',
          candidate_code: 'CAND-0001',
          original_filename: 'candidate.pdf',
          status: 'completed',
          segments: [],
        })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/jobs/job-1/pipeline')
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )

    fireEvent.click(await screen.findByRole('button', { name: /查看档案/ }))
    await waitFor(() => {
      expect(window.location.pathname).toBe(
        '/jobs/job-1/batches/batch-1/documents/document-1/history',
      )
    })
  })
})
