import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type {
  InterviewPlanDraftInput,
  InterviewPlanVersion,
  JobDetail,
} from './api/client'

const timestamp = '2026-07-26T12:00:00Z'
const user = {
  id: '03f8ba31-0a83-4466-bc4c-143bd3279680',
  username: 'recruiter',
  display_name: '招聘专员',
  is_active: true,
  must_change_password: false,
  roles: ['recruiter'],
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function job(status: 'active' | 'archived' = 'active'): JobDetail {
  return {
    id: 'job-interview',
    recruiter_id: user.id,
    hiring_manager_id: null,
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

function hydrateVersion(
  version: InterviewPlanVersion,
  payload: InterviewPlanDraftInput,
): InterviewPlanVersion {
  return {
    ...version,
    rounds: payload.rounds.map((round, roundIndex) => ({
      ...round,
      id: `round-${version.version_number}-${roundIndex}`,
      questions: round.questions.map((question, questionIndex) => ({
        ...question,
        id: `question-${version.version_number}-${roundIndex}-${questionIndex}`,
      })),
      scoring_dimensions: round.scoring_dimensions.map((dimension, dimensionIndex) => ({
        ...dimension,
        id: `dimension-${version.version_number}-${roundIndex}-${dimensionIndex}`,
        anchors: dimension.anchors.map((anchor) => ({
          ...anchor,
          id: `anchor-${version.version_number}-${roundIndex}-${dimensionIndex}-${anchor.score_value}`,
        })),
      })),
    })),
  }
}

function confirmedVersion(): InterviewPlanVersion {
  return hydrateVersion(
    {
      id: 'plan-1',
      job_id: 'job-interview',
      version_number: 1,
      status: 'confirmed',
      source_version_id: null,
      confirmed_by_id: user.id,
      confirmed_at: timestamp,
      created_at: timestamp,
      updated_at: timestamp,
      rounds: [],
    },
    {
      rounds: [
        {
          name: '技术一面',
          round_type: 'technical',
          duration_minutes: 60,
          pass_threshold: 70,
          focus: '系统设计与工程质量',
          sort_order: 0,
          questions: [
            {
              question_text: '请说明高并发系统的设计取舍。',
              evaluation_guide: '关注容量估算和故障降级。',
              sort_order: 0,
            },
          ],
          scoring_dimensions: [
            {
              name: '系统设计',
              description: '架构拆分与可靠性',
              weight_percent: 100,
              sort_order: 0,
              anchors: [1, 2, 3, 4, 5].map((score) => ({
                score_value: score,
                description: `系统设计${score}分表现`,
              })),
            },
          ],
        },
      ],
    },
  )
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

describe('interview plan and structured scorecard flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('创建、确认并基于不可变版本复制面试方案', async () => {
    let versions: InterviewPlanVersion[] = []
    const savedPayloads: InterviewPlanDraftInput[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-interview') return jsonResponse(job())
      if (path === '/api/jobs/job-interview/interview-plans/versions' && method === 'GET') {
        return jsonResponse([...versions].reverse())
      }
      if (path === '/api/jobs/job-interview/interview-plans/versions' && method === 'POST') {
        const body = JSON.parse(init?.body as string) as { source_version_id: string | null }
        const source = versions.find((item) => item.id === body.source_version_id)
        const version: InterviewPlanVersion = {
          id: `plan-${versions.length + 1}`,
          job_id: 'job-interview',
          version_number: versions.length + 1,
          status: 'draft',
          source_version_id: source?.id ?? null,
          confirmed_by_id: null,
          confirmed_at: null,
          created_at: timestamp,
          updated_at: timestamp,
          rounds: source ? hydrateVersion(source, { rounds: source.rounds }).rounds : [],
        }
        versions = [...versions, version]
        return jsonResponse(version, 201)
      }
      if (
        path === '/api/jobs/job-interview/interview-plans/versions/plan-1' &&
        method === 'PUT'
      ) {
        const savedPayload = JSON.parse(init?.body as string) as InterviewPlanDraftInput
        savedPayloads.push(savedPayload)
        versions = [hydrateVersion(versions[0], savedPayload)]
        return jsonResponse(versions[0])
      }
      if (
        path === '/api/jobs/job-interview/interview-plans/versions/plan-1/confirm' &&
        method === 'POST'
      ) {
        versions = [
          {
            ...versions[0],
            status: 'confirmed',
            confirmed_by_id: user.id,
            confirmed_at: timestamp,
          },
        ]
        return jsonResponse(versions[0])
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/jobs/job-interview/interview-plan')
    renderApp()

    expect(await screen.findByText('尚未建立面试方案')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /创建面试方案草稿/ }))
    expect(await screen.findByRole('heading', { name: '面试方案 V1' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /添加面试轮次/ }))
    fireEvent.click(screen.getByRole('button', { name: /保存草稿/ }))
    await waitFor(() => expect(savedPayloads).toHaveLength(1))
    expect(savedPayloads[0].rounds[0]).toMatchObject({
      name: '',
      questions: [],
      scoring_dimensions: [],
    })

    fireEvent.change(screen.getByLabelText('面试轮次 1 名称'), {
      target: { value: '技术一面' },
    })
    fireEvent.change(screen.getByLabelText('面试轮次 1 建议时长'), {
      target: { value: '60' },
    })
    fireEvent.change(screen.getByLabelText('面试轮次 1 通过线'), {
      target: { value: '70' },
    })
    fireEvent.change(screen.getByLabelText('面试轮次 1 考察重点'), {
      target: { value: '系统设计与工程质量' },
    })

    fireEvent.click(screen.getByRole('button', { name: /添加面试问题/ }))
    fireEvent.change(screen.getByLabelText('轮次 1 问题 1 正文'), {
      target: { value: '请说明高并发系统的设计取舍。' },
    })
    fireEvent.change(screen.getByLabelText('轮次 1 问题 1 评价参考要点'), {
      target: { value: '关注容量估算和故障降级。' },
    })

    fireEvent.click(screen.getByRole('button', { name: /添加评分维度/ }))
    fireEvent.change(screen.getByLabelText('轮次 1 评分维度 1 名称'), {
      target: { value: '系统设计' },
    })
    fireEvent.change(screen.getByLabelText('轮次 1 评分维度 1 权重'), {
      target: { value: '100' },
    })
    for (const score of [1, 2, 3, 4, 5]) {
      fireEvent.change(screen.getByLabelText(`轮次 1 评分维度 1 ${score} 分锚点`), {
        target: { value: `系统设计${score}分表现` },
      })
    }

    expect(await screen.findByText('当前权重 100%')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /确认方案/ }))
    fireEvent.click(await screen.findByRole('button', { name: '确认并锁定' }))

    expect(await screen.findByText('已确认版本不可修改')).toBeInTheDocument()
    expect(screen.getByText('系统设计1分表现')).toBeInTheDocument()
    expect(savedPayloads).toHaveLength(2)
    expect(savedPayloads[1].rounds[0]).toMatchObject({
      name: '技术一面',
      duration_minutes: 60,
      pass_threshold: 70,
    })
    expect(savedPayloads[1].rounds[0].scoring_dimensions[0].anchors).toHaveLength(5)

    fireEvent.click(screen.getByRole('button', { name: /基于此版本新建/ }))
    expect(await screen.findByRole('heading', { name: '面试方案 V2' })).toBeInTheDocument()
    expect(screen.getByText('草稿可继续编辑')).toBeInTheDocument()
    await waitFor(() => expect(versions).toHaveLength(2))
  })

  it('归档职位仍可查看已确认方案但不能创建新版本', async () => {
    const version = confirmedVersion()
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-interview') return jsonResponse(job('archived'))
      if (path === '/api/jobs/job-interview/interview-plans/versions') {
        return jsonResponse([version])
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/jobs/job-interview/interview-plan')
    renderApp()

    expect(await screen.findByText('该职位已归档，面试方案仅供查看')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '面试方案 V1' })).toBeInTheDocument()
    expect(screen.getByText(/技术一面/)).toBeInTheDocument()
    expect(screen.getByText(/请说明高并发系统的设计取舍。/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /基于此版本新建/ })).not.toBeInTheDocument()
  })
})
