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
          status: 'uploaded',
          failure_code: null,
          failure_message: null,
          attempt_count: 1,
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
          status: 'failed',
          failure_code: 'invalid_file_signature',
          failure_message: '文件特征不完整或文件已经损坏',
          attempt_count: 1,
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
          status: 'uploaded' as const,
          failure_code: null,
          failure_message: null,
          attempt_count: 2,
        }
        batches = [
          {
            ...partialBatch,
            status: 'ready',
            success_count: 2,
            failed_count: 0,
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

    expect(await screen.findByText('已选择 2 / 50 份')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /开始上传/ }))

    expect(await screen.findByRole('heading', { name: '7 月校招第一批' })).toBeInTheDocument()
    expect(screen.getByText('文件特征不完整或文件已经损坏')).toBeInTheDocument()
    const postCall = fetchMock.mock.calls.find(
      ([path, init]) => path === '/api/jobs/job-1/batches' && init?.method === 'POST',
    )
    expect(postCall?.[1]?.body).toBeInstanceOf(FormData)
    expect((postCall?.[1]?.body as FormData).getAll('files')).toHaveLength(2)

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
})
