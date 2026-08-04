import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AIConsolePage } from './pages/AIConsolePage'

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
      <AIConsolePage />
    </QueryClientProvider>,
  )
}

describe('AI 控制台页面', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('展示 AI 工程化专项入口、任务中心和调用日志', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(input.toString(), 'http://localhost')
      if (url.pathname === '/api/ai-observability/summary') {
        return json({
          task_total: 2,
          call_total: 3,
          failed_task_count: 1,
          failed_call_count: 1,
          total_input_tokens: 120,
          total_output_tokens: 30,
          total_tokens: 150,
          avg_task_duration_ms: 1000,
          avg_call_duration_ms: 800,
          task_status_counts: [{ key: 'failed', count: 1 }],
          call_status_counts: [{ key: 'succeeded', count: 2 }],
          call_scenario_counts: [{ key: 'resume_analysis', count: 2 }],
        })
      }
      if (url.pathname === '/api/ai-observability/tasks') {
        return json({
          items: [
            {
              id: 'task-1',
              celery_task_id: 'celery-1',
              task_name: 'resume.analyze',
              scenario: 'resume_analysis',
              status: 'failed',
              attempt_count: 2,
              max_retries: 3,
              resource_type: 'resume_document',
              resource_id: '11111111-1111-4111-8111-111111111111',
              job_id: null,
              batch_id: null,
              document_id: null,
              application_id: null,
              candidate_profile_id: null,
              failure_code: 'ai_timeout',
              failure_message: '模型请求超时',
              duration_ms: 1000,
              started_at: '2026-08-04T12:00:00Z',
              completed_at: '2026-08-04T12:00:01Z',
              created_at: '2026-08-04T12:00:00Z',
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        })
      }
      if (url.pathname === '/api/ai-observability/calls') {
        return json({
          items: [
            {
              id: 'call-1',
              task_id: 'task-1',
              scenario: 'jd_generation',
              status: 'succeeded',
              model_name: 'qwen-plus',
              prompt_version: 'jd-structure-v1',
              prompt_template_version_id: null,
              provider: 'openai_compatible',
              retry_count: 0,
              duration_ms: 800,
              input_tokens: 120,
              output_tokens: 30,
              total_tokens: 150,
              resource_type: 'job',
              resource_id: '22222222-2222-4222-8222-222222222222',
              job_id: null,
              batch_id: null,
              document_id: null,
              application_id: null,
              candidate_profile_id: null,
              failure_code: null,
              failure_message: null,
              created_at: '2026-08-04T12:00:00Z',
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        })
      }
      return json({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(screen.getByRole('heading', { name: 'AI Agent 工程化专项' })).toBeInTheDocument()
    expect(await screen.findByText('resume.analyze')).toBeInTheDocument()
    expect(screen.getByText('模型请求超时')).toBeInTheDocument()

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(fetchMock.mock.calls[0][0]).toBe('/api/ai-observability/summary')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/ai-observability/tasks?limit=20&offset=0')
    expect(fetchMock.mock.calls[2][0]).toBe('/api/ai-observability/calls?limit=20&offset=0')

    expect(screen.getByText('任务中心')).toBeInTheDocument()
    expect(screen.getByText('调用日志')).toBeInTheDocument()
    expect(screen.getByText('专项路线')).toBeInTheDocument()
    expect(screen.getByText('150')).toBeInTheDocument()
  })
})
