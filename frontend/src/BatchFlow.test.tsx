import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { ScreeningBatchRecord } from './api/client'

const timestamp = '2026-07-22T12:00:00Z'
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
  criteria_versions: [
    {
      id: 'version-1',
      job_id: 'job-1',
      version_number: 1,
      status: 'confirmed' as const,
      pass_threshold: 60,
      source_version_id: null,
      confirmed_by_id: 'user-1',
      confirmed_at: timestamp,
      created_at: timestamp,
      updated_at: timestamp,
      hard_requirements: [],
      scoring_dimensions: [],
    },
  ],
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('resume batch flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('支持混合批量上传、展示失败原因并重新上传', async () => {
    let batches: ScreeningBatchRecord[] = []
    const partialBatch: ScreeningBatchRecord = {
      id: 'batch-1',
      job_id: 'job-1',
      criteria_version_id: 'version-1',
      criteria_version_number: 1,
      name: '7 月校招第一批',
      ai_input_mode: 'raw',
      status: 'partial_failure',
      total_count: 2,
      success_count: 1,
      failed_count: 1,
      processing_count: 0,
      created_at: timestamp,
      updated_at: timestamp,
      documents: [
        {
          id: 'document-1',
          batch_id: 'batch-1',
          original_filename: 'resume.pdf',
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
          redaction_count: 0,
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
        },
        {
          id: 'document-2',
          batch_id: 'batch-1',
          original_filename: 'broken.png',
          file_extension: '',
          content_type: 'image/png',
          detected_type: '',
          size_bytes: 0,
          sha256: null,
          has_original_file: false,
          extraction_method: null,
          segment_count: 0,
          text_character_count: 0,
          candidate_code: 'CAND-0002',
          redaction_count: 0,
          status: 'failed',
          failure_code: 'invalid_file_signature',
          failure_message: '文件特征不完整或文件已经损坏',
          attempt_count: 1,
          processing_attempt_count: 0,
          processing_started_at: null,
          parsed_at: null,
          redacted_at: null,
          created_at: timestamp,
          updated_at: timestamp,
        },
      ],
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/batches' && method === 'GET') return jsonResponse(batches)
      if (path === '/api/jobs/job-1/batches' && method === 'POST') {
        batches = [partialBatch]
        return jsonResponse(partialBatch, 201)
      }
      if (
        path === '/api/jobs/job-1/batches/batch-1/documents/document-2/retry' &&
        method === 'PUT'
      ) {
        const retried = {
          ...partialBatch.documents[1],
          original_filename: 'replacement.png',
          file_extension: '.png',
          detected_type: 'png',
          size_bytes: 512,
          sha256: 'b'.repeat(64),
          has_original_file: true,
          status: 'queued' as const,
          failure_code: null,
          failure_message: null,
          attempt_count: 2,
        }
        batches = [
          {
            ...partialBatch,
            status: 'processing',
            success_count: 1,
            failed_count: 0,
            processing_count: 1,
            documents: [partialBatch.documents[0], retried],
          },
        ]
        return jsonResponse(retried)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/jobs/job-1/batches')
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: '平台工程师' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('批次名称'), {
      target: { value: '7 月校招第一批' },
    })
    const uploadInput = container.querySelector<HTMLInputElement>('input[type="file"]')
    expect(uploadInput).not.toBeNull()
    const validFile = new File(['pdf'], 'resume.pdf', { type: 'application/pdf' })
    const invalidFile = new File(['broken'], 'broken.png', { type: 'image/png' })
    fireEvent.change(uploadInput!, { target: { files: [validFile, invalidFile] } })

    expect(await screen.findByText('单批最多 50 份，单文件不超过 20 MB')).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'AI 输入方式' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(screen.getByText('发送原文（默认）')).toBeInTheDocument()
    expect(await screen.findByText('已选择 2 / 50 份')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /开始上传/ }))

    expect(await screen.findByRole('heading', { name: '7 月校招第一批' })).toBeInTheDocument()
    expect(screen.getByText('文件特征不完整或文件已经损坏')).toBeInTheDocument()
    const postCall = fetchMock.mock.calls.find(
      ([path, init]) => path === '/api/jobs/job-1/batches' && init?.method === 'POST',
    )
    expect(postCall?.[1]?.body).toBeInstanceOf(FormData)
    expect((postCall?.[1]?.body as FormData).getAll('files')).toHaveLength(2)
    expect((postCall?.[1]?.body as FormData).get('ai_input_mode')).toBe('raw')

    const fileInputs = container.querySelectorAll<HTMLInputElement>('input[type="file"]')
    expect(fileInputs.length).toBeGreaterThan(1)
    fireEvent.change(fileInputs[fileInputs.length - 1], {
      target: {
        files: [new File(['png'], 'replacement.png', { type: 'image/png' })],
      },
    })

    await waitFor(() => expect(screen.queryByText('文件特征不完整或文件已经损坏')).toBeNull())
    expect(await screen.findByText('replacement.png')).toBeInTheDocument()
    expect(screen.getByText(/第 2 次尝试/)).toBeInTheDocument()
  })

  it('创建批次时可以选择脱敏后发送', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/batches' && method === 'GET') return jsonResponse([])
      if (path === '/api/jobs/job-1/batches' && method === 'POST') {
        expect((init?.body as FormData).get('ai_input_mode')).toBe('redacted')
        return jsonResponse(
          {
            id: 'batch-redacted',
            job_id: 'job-1',
            criteria_version_id: 'version-1',
            criteria_version_number: 1,
            name: '简历筛选批次',
            ai_input_mode: 'redacted',
            status: 'processing',
            total_count: 1,
            success_count: 0,
            failed_count: 0,
            processing_count: 1,
            created_at: timestamp,
            updated_at: timestamp,
            documents: [],
          },
          201,
        )
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/jobs/job-1/batches')
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: '平台工程师' })).toBeInTheDocument()
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'AI 输入方式' }))
    fireEvent.click(await screen.findByRole('option', { name: '脱敏后发送' }))
    const uploadInput = container.querySelector<HTMLInputElement>('input[type="file"]')
    fireEvent.change(uploadInput!, {
      target: { files: [new File(['pdf'], 'resume.pdf', { type: 'application/pdf' })] },
    })
    expect(await screen.findByText('已选择 1 / 50 份')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /开始上传/ }))

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([path, init]) => path === '/api/jobs/job-1/batches' && init?.method === 'POST',
        ),
      ).toBe(true),
    )
  })

  it('单批选择超过 50 份时只保留前 50 份', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/batches') return jsonResponse([])
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/jobs/job-1/batches')
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: '平台工程师' })).toBeInTheDocument()
    const uploadInput = container.querySelector<HTMLInputElement>('input[type="file"]')
    expect(uploadInput).not.toBeNull()
    const tooManyFiles = Array.from(
      { length: 51 },
      (_, index) => new File(['pdf'], `resume-${index}.pdf`, { type: 'application/pdf' }),
    )
    fireEvent.change(uploadInput!, { target: { files: tooManyFiles } })

    expect(await screen.findByText('已选择 50 / 50 份')).toBeInTheDocument()
  })

  it('展示解析片段并支持保留原文件的失败任务重新处理', async () => {
    const completedDocument = {
      id: 'document-completed',
      batch_id: 'batch-parse',
      original_filename: 'backend.pdf',
      file_extension: '.pdf',
      content_type: 'application/pdf',
      detected_type: 'pdf',
      size_bytes: 2048,
      sha256: 'c'.repeat(64),
      has_original_file: true,
      extraction_method: 'pdf_text',
      segment_count: 1,
      text_character_count: 35,
      candidate_code: 'CAND-0003',
      redaction_count: 1,
      status: 'completed' as const,
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
    const failedDocument = {
      ...completedDocument,
      id: 'document-failed',
      original_filename: 'scan.pdf',
      extraction_method: null,
      segment_count: 0,
      text_character_count: 0,
      status: 'failed' as const,
      failure_code: 'empty_text',
      failure_message: '未识别到有效文本',
      processing_attempt_count: 1,
      parsed_at: null,
      redacted_at: null,
    }
    let batch: ScreeningBatchRecord = {
      id: 'batch-parse',
      job_id: 'job-1',
      criteria_version_id: 'version-1',
      criteria_version_number: 1,
      name: '解析验证批次',
      ai_input_mode: 'raw',
      status: 'partial_failure',
      total_count: 2,
      success_count: 1,
      failed_count: 1,
      processing_count: 0,
      created_at: timestamp,
      updated_at: timestamp,
      documents: [completedDocument, failedDocument],
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/batches') return jsonResponse([batch])
      if (
        path ===
          '/api/jobs/job-1/batches/batch-parse/documents/document-completed' &&
        method === 'GET'
      ) {
        return jsonResponse({
          ...completedDocument,
          text_segments: [
            {
              id: 'segment-1',
              document_id: completedDocument.id,
              segment_key: 'SEG-0001',
              source_type: 'pdf_page',
              source_index: 1,
              page_number: 1,
              paragraph_index: null,
              raw_text: 'Python FastAPI PostgreSQL',
              normalized_text: 'Python FastAPI PostgreSQL',
              redacted_text: 'Python FastAPI PostgreSQL',
              ocr_confidence: null,
              sort_order: 0,
            },
          ],
        })
      }
      if (
        path === '/api/jobs/job-1/batches/batch-parse/documents/document-failed/parse-retry' &&
        method === 'POST'
      ) {
        const queued = {
          ...failedDocument,
          status: 'queued' as const,
          failure_code: null,
          failure_message: null,
        }
        batch = {
          ...batch,
          status: 'processing',
          failed_count: 0,
          processing_count: 1,
          documents: [completedDocument, queued],
        }
        return jsonResponse(queued)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/jobs/job-1/batches')
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: '解析验证批次' })).toBeInTheDocument()
    expect(screen.getByText('解析失败')).toBeInTheDocument()
    expect(screen.getByText('未识别到有效文本')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /查看文本/ }))
    expect(await screen.findAllByText('Python FastAPI PostgreSQL')).toHaveLength(2)
    expect(screen.getAllByText('PDF 文本提取')).not.toHaveLength(0)
    expect(screen.getByText('PDF 第 1 页')).toBeInTheDocument()
    expect(screen.getByText('SEG-0001')).toBeInTheDocument()
    expect(screen.getAllByText('CAND-0003')).not.toHaveLength(0)
    expect(screen.getByText('1 项')).toBeInTheDocument()
    expect(screen.getByText('查看授权原文证据')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /重新处理/ }))
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([path, init]) =>
            path ===
              '/api/jobs/job-1/batches/batch-parse/documents/document-failed/parse-retry' &&
            init?.method === 'POST',
        ),
      ).toBe(true),
    )
    expect(await screen.findByText('等待解析')).toBeInTheDocument()
  })

  it('要求输入永久删除后删除批次并刷新列表', async () => {
    const batch: ScreeningBatchRecord = {
      id: 'batch-delete',
      job_id: 'job-1',
      criteria_version_id: 'version-1',
      criteria_version_number: 1,
      name: '待删除批次',
      ai_input_mode: 'raw',
      status: 'completed',
      total_count: 1,
      success_count: 1,
      failed_count: 0,
      processing_count: 0,
      created_at: timestamp,
      updated_at: timestamp,
      documents: [],
    }
    let batches = [batch]
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/batches' && method === 'GET') {
        return jsonResponse(batches)
      }
      if (path === '/api/jobs/job-1/batches/batch-delete' && method === 'DELETE') {
        expect(JSON.parse(String(init?.body))).toEqual({ confirmation: '永久删除' })
        batches = []
        return jsonResponse({
          status: 'deleted',
          batch_id: 'batch-delete',
          deleted_document_count: 1,
          deleted_file_count: 1,
          message: null,
        })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/jobs/job-1/batches')
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: '待删除批次' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /永久删除/ }))
    const confirmButton = await screen.findByRole('button', { name: '确认永久删除' })
    expect(confirmButton).toBeDisabled()
    const confirmation = screen.getByLabelText('请输入“永久删除”确认操作')
    fireEvent.change(confirmation, { target: { value: '确认' } })
    expect(confirmButton).toBeDisabled()
    fireEvent.change(confirmation, { target: { value: '永久删除' } })
    expect(confirmButton).toBeEnabled()
    fireEvent.click(confirmButton)

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([path, init]) =>
            path === '/api/jobs/job-1/batches/batch-delete' && init?.method === 'DELETE',
        ),
      ).toBe(true),
    )
    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: '待删除批次' })).toBeNull(),
    )
    expect(await screen.findByText('还没有简历批次')).toBeInTheDocument()
  })

  it('永久删除失败时保留批次并展示错误', async () => {
    const batch: ScreeningBatchRecord = {
      id: 'batch-delete-failure',
      job_id: 'job-1',
      criteria_version_id: 'version-1',
      criteria_version_number: 1,
      name: '删除失败批次',
      ai_input_mode: 'raw',
      status: 'completed',
      total_count: 1,
      success_count: 1,
      failed_count: 0,
      processing_count: 0,
      created_at: timestamp,
      updated_at: timestamp,
      documents: [],
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(job)
      if (path === '/api/jobs/job-1/batches' && method === 'GET') {
        return jsonResponse([batch])
      }
      if (
        path === '/api/jobs/job-1/batches/batch-delete-failure' &&
        method === 'DELETE'
      ) {
        return jsonResponse({ detail: '原始文件删除准备失败，批次数据未删除' }, 500)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/jobs/job-1/batches')
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: '删除失败批次' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /永久删除/ }))
    fireEvent.change(screen.getByLabelText('请输入“永久删除”确认操作'), {
      target: { value: '永久删除' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认永久删除' }))

    expect(
      await screen.findByText('原始文件删除准备失败，批次数据未删除'),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '删除失败批次' })).toBeInTheDocument()
  })
})
