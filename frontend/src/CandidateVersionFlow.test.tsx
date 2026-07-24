import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type {
  CandidateProfileRecord,
  ResumeDocumentRecord,
  ScreeningBatchRecord,
  ScreeningResultDetail,
} from './api/client'

const timestamp = '2026-07-23T04:00:00Z'
const user = { id: 'user-1', username: 'recruiter', display_name: '招聘专员' }
const criteriaVersions = [
  {
    id: 'criteria-2',
    job_id: 'job-1',
    version_number: 2,
    status: 'confirmed' as const,
    pass_threshold: 70,
    source_version_id: 'criteria-1',
    confirmed_by_id: user.id,
    confirmed_at: timestamp,
    created_at: timestamp,
    updated_at: timestamp,
    hard_requirements: [],
    scoring_dimensions: [],
  },
  {
    id: 'criteria-1',
    job_id: 'job-1',
    version_number: 1,
    status: 'confirmed' as const,
    pass_threshold: 60,
    source_version_id: null,
    confirmed_by_id: user.id,
    confirmed_at: timestamp,
    created_at: timestamp,
    updated_at: timestamp,
    hard_requirements: [],
    scoring_dimensions: [],
  },
]
const job = {
  id: 'job-1',
  title: '平台工程师',
  department: '研发中心',
  original_jd: '负责平台工程建设。',
  status: 'active' as const,
  archived_at: null,
  created_at: timestamp,
  updated_at: timestamp,
  criteria_versions: criteriaVersions,
}
const document: ResumeDocumentRecord = {
  id: 'document-1',
  batch_id: 'batch-1',
  original_filename: 'candidate.pdf',
  file_extension: '.pdf',
  content_type: 'application/pdf',
  detected_type: 'pdf',
  size_bytes: 1024,
  sha256: 'a'.repeat(64),
  has_original_file: true,
  extraction_method: 'pdf_text',
  segment_count: 1,
  text_character_count: 120,
  candidate_code: 'CAND-0001',
  redaction_count: 2,
  status: 'completed',
  failure_code: null,
  failure_message: null,
  attempt_count: 1,
  processing_attempt_count: 1,
  processing_started_at: timestamp,
  parsed_at: timestamp,
  redacted_at: timestamp,
  created_at: timestamp,
  updated_at: timestamp,
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function profile(
  id: string,
  versionNumber: number,
  source: 'ai' | 'manual',
  sourceProfileId: string | null,
): CandidateProfileRecord {
  return {
    id,
    document_id: document.id,
    version_number: versionNumber,
    source,
    source_profile_id: sourceProfileId,
    model_name: source === 'manual' ? 'manual-correction' : 'stub-model',
    prompt_version: source === 'manual' ? 'profile-correction-v1' : 'resume-match-v1',
    education: [],
    work_experiences: [],
    projects: [],
    skills: [{ name: versionNumber === 1 ? 'Python' : 'Python / FastAPI', evidence: [] }],
    certifications: [],
    languages: [],
    created_at: timestamp,
  }
}

function analysis(
  id: string,
  analysisVersion: number,
  status: 'completed' | 'failed',
  candidateProfile: CandidateProfileRecord,
): ScreeningResultDetail {
  return {
    id,
    document_id: document.id,
    candidate_code: document.candidate_code,
    criteria_version_id: 'criteria-1',
    criteria_version_number: 1,
    analysis_version: analysisVersion,
    status,
    ai_group: status === 'completed' ? 'passed' : null,
    total_score: status === 'completed' ? 86 : null,
    pass_threshold: 60,
    hard_requirements: [],
    strengths: status === 'completed' ? ['平台工程经验'] : [],
    gaps: [],
    missing_items: [],
    interview_questions: [],
    model_name: 'stub-model',
    prompt_version: 'resume-match-v1',
    failure_code: status === 'failed' ? 'ai_upstream_failed' : null,
    failure_message: status === 'failed' ? '模型暂时不可用' : null,
    started_at: timestamp,
    completed_at: timestamp,
    created_at: timestamp,
    candidate_profile: candidateProfile,
    dimension_scores: [],
    evidence: [],
    current_decision: 'unprocessed',
    decision_history: [],
  }
}

function renderApp(path: string) {
  window.history.replaceState({}, '', path)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

describe('candidate profile versions and reanalysis flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('保留档案与分析历史，并只修正和重跑目标候选人', async () => {
    const profileV1 = profile('profile-1', 1, 'ai', null)
    let profiles = [profileV1]
    const histories = [
      analysis('result-failed', 2, 'failed', profileV1),
      analysis('result-completed', 1, 'completed', profileV1),
    ]
    const correctionBodies: Record<string, unknown>[] = []
    const reanalysisBodies: Record<string, unknown>[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/batches/batch-1/documents/document-1') {
        return jsonResponse({ ...document, text_segments: [] })
      }
      if (
        path === '/api/jobs/job-1/batches/batch-1/documents/document-1/profiles' &&
        method === 'GET'
      ) {
        return jsonResponse(profiles)
      }
      if (
        path === '/api/jobs/job-1/batches/batch-1/documents/document-1/analysis-history' &&
        method === 'GET'
      ) {
        return jsonResponse(histories)
      }
      if (
        path === '/api/jobs/job-1/batches/batch-1/documents/document-1/profile-corrections' &&
        method === 'POST'
      ) {
        const body = JSON.parse(init?.body as string) as Record<string, unknown>
        correctionBodies.push(body)
        const profileV2 = {
          ...profile('profile-2', 2, 'manual', 'profile-1'),
          skills: body.skills as Record<string, unknown>[],
        }
        profiles = [profileV2, profileV1]
        return jsonResponse(
          {
            profile: profileV2,
            reanalysis: {
              status: 'queued',
              document_id: document.id,
              criteria_version_id: body.criteria_version_id,
              analysis_version: 3,
              candidate_profile_id: profileV2.id,
              task_id: 'task-correction',
              message: null,
            },
          },
          201,
        )
      }
      if (
        path === '/api/jobs/job-1/batches/batch-1/documents/document-1/reanalysis' &&
        method === 'POST'
      ) {
        const body = JSON.parse(init?.body as string) as Record<string, unknown>
        reanalysisBodies.push(body)
        return jsonResponse(
          {
            status: 'queued',
            document_id: document.id,
            criteria_version_id: body.criteria_version_id,
            analysis_version: 4,
            candidate_profile_id: body.candidate_profile_id,
            task_id: 'task-single',
            message: null,
          },
          202,
        )
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/jobs/job-1/batches/batch-1/documents/document-1/history')

    expect(await screen.findByRole('heading', { name: 'CAND-0001' })).toBeInTheDocument()
    expect(screen.getByText('档案 V1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /分析历史/ }))
    expect(await screen.findByText('模型暂时不可用')).toBeInTheDocument()
    expect(screen.getByText('失败记录会保留，但不会覆盖此前已经完成的可用结果。')).toBeInTheDocument()
    expect(screen.getByText('86.0')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: /资料版本/ }))
    fireEvent.click(screen.getByRole('button', { name: /修正结构化资料/ }))
    fireEvent.change(screen.getByLabelText('技能（JSON 数组）'), {
      target: { value: '[{"name":"Python / FastAPI","evidence":[]}]' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存新版本并重新分析' }))

    expect(await screen.findByText('档案 V2')).toBeInTheDocument()
    expect(correctionBodies).toHaveLength(1)
    expect(correctionBodies[0]).toMatchObject({
      source_profile_id: 'profile-1',
      criteria_version_id: 'criteria-1',
      skills: [{ name: 'Python / FastAPI', evidence: [] }],
    })
    expect(fetchMock.mock.calls.some(([path]) => path.toString().includes('document-2'))).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: /单人重新分析/ }))
    fireEvent.click(screen.getByRole('button', { name: '确认重跑' }))
    await waitFor(() => expect(reanalysisBodies).toHaveLength(1))
    expect(reanalysisBodies[0]).toMatchObject({
      criteria_version_id: 'criteria-1',
      candidate_profile_id: 'profile-2',
    })
  })

  it('使用指定标准为整批候选人创建统一分析版本并展示处理数量', async () => {
    const skippedDocument: ResumeDocumentRecord = {
      ...document,
      id: 'document-2',
      candidate_code: 'CAND-0002',
      original_filename: 'pending.pdf',
      status: 'processing',
      redacted_at: null,
    }
    const batch: ScreeningBatchRecord = {
      id: 'batch-1',
      job_id: job.id,
      criteria_version_id: 'criteria-1',
      criteria_version_number: 1,
      name: '历史候选人批次',
      ai_input_mode: 'raw',
      status: 'processing',
      total_count: 2,
      success_count: 1,
      failed_count: 0,
      processing_count: 1,
      created_at: timestamp,
      updated_at: timestamp,
      documents: [document, skippedDocument],
    }
    const batchBodies: Record<string, unknown>[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/batches' && method === 'GET') return jsonResponse([batch])
      if (path === '/api/jobs/job-1/batches/batch-1/reanalysis' && method === 'POST') {
        const body = JSON.parse(init?.body as string) as Record<string, unknown>
        batchBodies.push(body)
        return jsonResponse(
          {
            status: 'partial_failure',
            batch_id: batch.id,
            criteria_version_id: body.criteria_version_id,
            analysis_version: 3,
            queued_count: 1,
            failed_count: 0,
            skipped_count: 1,
            tasks: [],
          },
          202,
        )
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/jobs/job-1/batches')

    expect(await screen.findByRole('heading', { name: '历史候选人批次' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /资料与版本/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /整批重新分析/ }))
    fireEvent.click(screen.getByRole('button', { name: '确认整批重跑' }))

    await waitFor(() => expect(batchBodies).toHaveLength(1))
    expect(batchBodies[0]).toEqual({ criteria_version_id: 'criteria-2' })
    expect(await screen.findByText('分析 V3 已创建')).toBeInTheDocument()
    expect(
      screen.getByText('排队 1 份，创建失败 0 份，跳过 1 份。所有旧分析结果继续保留。'),
    ).toBeInTheDocument()
  })
})
