import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AIEvaluationPage } from './pages/AIEvaluationPage'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AIEvaluationPage />
    </QueryClientProvider>,
  )
}

const dataset = {
  id: 'dataset-1',
  code: 'resume-analysis-synthetic-v1',
  name: '简历评分固定合成评测集',
  scenario: 'resume_analysis',
  description: '固定合成样本',
  version_number: 1,
  status: 'active',
  created_by_id: null,
  created_at: '2026-08-05T00:00:00Z',
  updated_at: '2026-08-05T00:00:00Z',
}

const run = {
  id: 'run-1',
  dataset_id: 'dataset-1',
  name: '简历评分固定合成评测集 / synthetic-baseline-v1',
  scenario: 'resume_analysis',
  status: 'failed',
  provider: 'local_deterministic',
  model_name: 'deterministic-evaluator',
  prompt_template_version_id: null,
  prompt_version: 'synthetic-baseline-v1',
  run_config: {},
  metrics_summary: { pass_rate: 0.96 },
  total_samples: 30,
  completed_samples: 30,
  passed_samples: 29,
  failed_samples: 1,
  average_score: 0.96,
  duration_ms: 88,
  failure_code: null,
  failure_message: null,
  created_by_id: null,
  started_at: '2026-08-05T00:00:00Z',
  completed_at: '2026-08-05T00:00:01Z',
  created_at: '2026-08-05T00:00:00Z',
  updated_at: '2026-08-05T00:00:01Z',
}

describe('AIEvaluationPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('展示评测运行和错误案例，并能启动离线评测', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(input.toString(), 'http://localhost')
      if (url.pathname === '/api/ai-evaluations/datasets') return json({ items: [dataset] })
      if (url.pathname === '/api/ai-evaluations/datasets/default-resume') return json(dataset, 201)
      if (url.pathname === '/api/ai-evaluations/runs') return json({ total: 1, items: [run] })
      if (url.pathname === '/api/ai-evaluations/runs/offline-resume') return json(run, 201)
      if (url.pathname === '/api/ai-evaluations/runs/run-1') {
        return json({
          run,
          results: [
            {
              id: 'result-1',
              run_id: 'run-1',
              sample_id: 'sample-1',
              status: 'failed',
              score: 0.35,
              actual_output: { recommendation: 'reject' },
              expected_snapshot: { expected_recommendation: 'recommend' },
              error_types: ['wrong_recommendation'],
              evidence_coverage_score: 0,
              format_valid: true,
              recommendation_matched: false,
              ai_call_log_id: null,
              duration_ms: 8,
              input_tokens: 10,
              output_tokens: 5,
              total_tokens: 15,
              failure_code: null,
              failure_message: null,
              created_at: '2026-08-05T00:00:00Z',
            },
          ],
        })
      }
      if (url.pathname === '/api/ai-evaluations/error-cases') {
        return json({
          total: 1,
          items: [
            {
              id: 'case-1',
              result_id: 'result-1',
              dataset_id: 'dataset-1',
              run_id: 'run-1',
              sample_id: 'sample-1',
              error_type: 'wrong_recommendation',
              severity: 'high',
              status: 'open',
              title: 'BE-01：推荐结论错误',
              description: '实际推荐结论与评测期望不一致',
              expected_behavior: '应输出 recommend',
              actual_behavior: 'reject',
              remediation_note: null,
              created_by_id: null,
              resolved_by_id: null,
              resolved_at: null,
              created_at: '2026-08-05T00:00:00Z',
              updated_at: '2026-08-05T00:00:00Z',
            },
          ],
        })
      }
      if (url.pathname === '/api/ai-evaluations/error-cases/case-1') {
        return json({ status: 'resolved' })
      }
      return json({ detail: `not found: ${url.pathname}`, init }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(screen.getByRole('heading', { name: 'AI 评测与错误案例库' })).toBeInTheDocument()
    expect(await screen.findByText('简历评分固定合成评测集 / synthetic-baseline-v1')).toBeInTheDocument()
    fireEvent.click(screen.getByText('错误案例库'))
    expect(await screen.findByText('BE-01：推荐结论错误')).toBeInTheDocument()

    fireEvent.click(screen.getByText('运行离线评测'))
    fireEvent.click(await screen.findByText('开始评测'))

    await waitFor(() =>
      expect(fetchMock.mock.calls.some((call) => call[0] === '/api/ai-evaluations/runs/offline-resume')).toBe(
        true,
      ),
    )
  })
})
