import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type {
  CandidateProcessCardRecord,
  InterviewReportContext,
  InterviewReportRecord,
  InterviewReportVersion,
  JobDetail,
} from './api/client'

const timestamp = '2026-07-28T12:00:00Z'
const detailPath = '/api/jobs/job-1/applications/application-1/interview-report'

const recruiter = {
  id: 'recruiter-1',
  username: 'recruiter',
  display_name: '招聘专员',
  is_active: true,
  must_change_password: false,
  roles: ['recruiter'],
}
const manager = {
  ...recruiter,
  id: 'manager-1',
  username: 'manager',
  display_name: '用人经理',
  roles: ['hiring_manager'],
}

const job: JobDetail = {
  id: 'job-1',
  recruiter_id: recruiter.id,
  hiring_manager_id: manager.id,
  recruitment_request_id: null,
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
  application_id: 'application-1',
  screening_result_id: 'screening-1',
  batch_id: 'batch-1',
  batch_name: '社招批次',
  document_id: 'document-1',
  candidate_code: 'CAND-0001',
  original_filename: 'candidate.pdf',
  phone: '13800138000',
  ai_group: 'passed',
  total_score: 86,
  current_decision: 'shortlisted',
  current_stage: 'to_interview',
  stage_entered_at: timestamp,
  skills: ['Python'],
  analysis_created_at: timestamp,
  onboarding: null,
  interview_evaluation: {
    status: 'in_progress',
    total_rounds: 2,
    submitted_count: 1,
    draft_count: 0,
    pending_count: 1,
    cancelled_count: 0,
    action_round_id: 'round-2',
    action_round_name: '业务二面',
    action_evaluation_status: 'not_started',
  },
}

const context: InterviewReportContext = {
  application_id: 'application-1',
  application_status: 'active',
  job_id: 'job-1',
  job_title: job.title,
  candidate_id: 'candidate-1',
  candidate_code: candidate.candidate_code,
  candidate_name: '张明',
  latest_screening: {
    id: 'screening-1',
    document_id: 'document-1',
    criteria_version_id: 'criteria-1',
    analysis_version: 2,
    ai_group: 'passed',
    total_score: 86,
    pass_threshold: 70,
    current_decision: 'shortlisted',
    strengths: ['系统设计证据充分'],
    gaps: ['业务经验待确认'],
    missing_items: [],
    completed_at: timestamp,
    citations: [
      {
        id: 'citation-1',
        subject_type: 'profile',
        subject_key: 'work_experience',
        quote: '负责核心交易系统重构',
        source_type: 'raw',
        page_number: 1,
        paragraph_index: 2,
      },
    ],
  },
  submitted_evaluations: [
    {
      evaluation_id: 'evaluation-1',
      round_id: 'round-1',
      round_name: '技术一面',
      round_type: 'technical',
      sort_order: 0,
      total_score: 84,
      passed: true,
      overall_recommendation: 'recommend',
      overall_comment: '系统设计能力达到岗位要求。',
      submitted_at: timestamp,
      question_responses: [
        {
          question_id: 'question-1',
          question_text: '请介绍一次系统重构',
          answer_summary: '完成单体到服务化重构。',
          evidence: '能够解释灰度与回滚取舍。',
        },
      ],
      dimension_ratings: [
        {
          dimension_id: 'dimension-1',
          dimension_name: '系统设计',
          score: 4,
          evidence: '方案完整且有量化结果。',
        },
      ],
    },
  ],
  missing_rounds: [
    {
      round_id: 'round-2',
      round_name: '业务二面',
      round_type: 'business',
      sort_order: 1,
      round_status: 'scheduled',
      reason: 'not_submitted',
    },
  ],
}

function version(
  versionNumber: number,
  overrides: Partial<InterviewReportVersion> = {},
): InterviewReportVersion {
  return {
    id: `version-${versionNumber}`,
    version_number: versionNumber,
    source_version_id: versionNumber === 1 ? null : `version-${versionNumber - 1}`,
    generation_mode: versionNumber === 1 ? 'ai' : 'manual',
    conclusion: 'next_round',
    executive_summary: '技术能力达到要求，建议完成业务面后再决策。',
    strengths: ['系统设计证据充分'],
    concerns: ['业务面评价尚未提交'],
    follow_up_actions: ['完成业务面'],
    screening_result_id: 'screening-1',
    evaluation_ids: ['evaluation-1'],
    evidence_snapshot: context,
    missing_rounds: context.missing_rounds,
    model_name: versionNumber === 1 ? 'test-model' : null,
    prompt_version: versionNumber === 1 ? 'interview-report-v1' : null,
    ai_failure_code: null,
    ai_failure_message: null,
    created_by_id: recruiter.id,
    created_by_username: recruiter.username,
    created_by_display_name: recruiter.display_name,
    created_at: timestamp,
    ...overrides,
  }
}

function reportRecord(versions: InterviewReportVersion[]): InterviewReportRecord {
  return {
    id: 'report-1',
    application_id: context.application_id,
    application_status: 'active',
    job_id: job.id,
    job_title: job.title,
    candidate_id: context.candidate_id,
    candidate_code: context.candidate_code,
    candidate_name: context.candidate_name,
    status: 'draft',
    current_version_number: versions.at(-1)!.version_number,
    confirmed_by_id: null,
    confirmed_at: null,
    created_at: timestamp,
    updated_at: timestamp,
    versions,
  }
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
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

function commonResponse(path: string, activeUser = recruiter): Response | undefined {
  if (path === '/api/auth/me') return jsonResponse(activeUser)
  if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
  if (path === '/api/jobs?include_archived=true') return jsonResponse([job])
  if (path === '/api/jobs/job-1') return jsonResponse(job)
  if (path === '/api/jobs/job-1/candidate-processes') return jsonResponse([candidate])
  if (path === `${detailPath}/context`) return jsonResponse(context)
  return undefined
}

describe('interview report flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('从面试报告列表进入尚未创建的候选人报告', async () => {
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    })))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const common = commonResponse(path)
      if (common) return common
      if (path === '/api/jobs/job-1/interview-reports') return jsonResponse([])
      if (path === detailPath) return jsonResponse({ detail: '面试报告不存在' }, 404)
      return jsonResponse({ detail: 'not found' }, 404)
    }))
    window.history.replaceState({}, '', '/jobs/job-1/interview-reports')
    renderApp()

    expect(await screen.findByRole('heading', { name: job.title })).toBeInTheDocument()
    expect(screen.getByText('未创建')).toBeInTheDocument()
    const startButton = screen.getByRole('button', { name: /开始报告/ })
    expect(startButton.closest('tr')).toHaveTextContent(/1\/2\s*轮已提交/)
    fireEvent.click(startButton)

    await waitFor(() => expect(window.location.pathname).toBe(
      '/jobs/job-1/applications/application-1/interview-report',
    ))
    expect(await screen.findByRole('heading', { name: '尚未创建面试报告' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /AI 生成草稿/ })).toBeInTheDocument()
    expect(screen.getByText('负责核心交易系统重构')).toBeInTheDocument()
  })

  it('生成 AI 草稿、保存 V2、确认锁定并查看历史版本', async () => {
    let savedReport: InterviewReportRecord | null = null
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      const common = commonResponse(path)
      if (common) return common
      if (path === '/api/jobs/job-1/interview-reports') return jsonResponse([])
      if (path === detailPath && method === 'GET') {
        return savedReport
          ? jsonResponse(savedReport)
          : jsonResponse({ detail: '面试报告不存在' }, 404)
      }
      if (path === `${detailPath}/ai-draft` && method === 'POST') {
        savedReport = reportRecord([version(1)])
        return jsonResponse(savedReport, 201)
      }
      if (path === `${detailPath}/versions` && method === 'POST') {
        const payload = JSON.parse(init?.body as string) as {
          executive_summary: string
          conclusion: 'next_round'
          strengths: string[]
          concerns: string[]
          follow_up_actions: string[]
        }
        const next = version(2, payload)
        savedReport = reportRecord([version(1), next])
        return jsonResponse(savedReport, 201)
      }
      if (path === `${detailPath}/confirm` && method === 'POST') {
        savedReport = {
          ...savedReport!,
          status: 'confirmed',
          confirmed_by_id: recruiter.id,
          confirmed_at: timestamp,
        }
        return jsonResponse(savedReport)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState(
      {},
      '',
      '/jobs/job-1/applications/application-1/interview-report',
    )
    renderApp()

    expect(await screen.findByRole('heading', { name: '尚未创建面试报告' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /AI 生成草稿/ }))
    expect(await screen.findByRole('heading', { name: '面试报告 V1' })).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('执行摘要'), {
      target: { value: '技术证据完整，建议完成业务面后进入录用决策。' },
    })
    fireEvent.click(screen.getByRole('button', { name: /保存新版本/ }))
    expect(await screen.findByRole('heading', { name: '面试报告 V2' })).toBeInTheDocument()
    expect(screen.getAllByText('V1').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: /确认报告/ }))
    fireEvent.click(await screen.findByRole('button', { name: '确认并锁定' }))
    expect(await screen.findByText('报告已确认并锁定')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /保存新版本/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /V1 AI 草稿/ }))
    expect(await screen.findByText('正在查看历史版本 V1')).toBeInTheDocument()
    expect(await screen.findByLabelText('执行摘要')).toBeDisabled()
    expect(savedReport).toMatchObject({
      status: 'confirmed',
      current_version_number: 2,
    })
    expect(fetchMock).toHaveBeenCalledWith(
      `${detailPath}/confirm`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ version_id: 'version-2' }),
      }),
    )
  })

  it('用人经理只能查看报告，不能修改或确认', async () => {
    const existing = reportRecord([version(1)])
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      const common = commonResponse(path, manager)
      if (common) return common
      if (path === detailPath) return jsonResponse(existing)
      if (path === '/api/jobs/job-1/interview-reports') return jsonResponse([])
      return jsonResponse({ detail: 'not found' }, 404)
    }))
    window.history.replaceState(
      {},
      '',
      '/jobs/job-1/applications/application-1/interview-report',
    )
    renderApp()

    expect(await screen.findByText('当前角色可查看面试报告，但不能创建、修改或确认')).toBeInTheDocument()
    expect(await screen.findByLabelText('执行摘要')).toBeDisabled()
    expect(screen.queryByRole('button', { name: /保存新版本/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /确认报告/ })).not.toBeInTheDocument()
  })
})
