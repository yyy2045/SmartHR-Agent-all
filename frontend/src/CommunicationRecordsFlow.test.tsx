import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { CommunicationRecordsPage } from './pages/CommunicationRecordsPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const communicationSummary = {
  id: '11111111-1111-1111-1111-111111111111',
  application_id: '22222222-2222-2222-2222-222222222222',
  candidate_id: '33333333-3333-3333-3333-333333333333',
  job_id: '44444444-4444-4444-4444-444444444444',
  context_type: 'offer',
  context_id: '55555555-5555-5555-5555-555555555555',
  record_kind: 'sent',
  channel: 'sms',
  channel_detail: null,
  recipient_masked: '138****0000',
  candidate_name_snapshot: '张三',
  subject_snapshot: 'Offer 通知',
  sent_at: '2026-08-02T08:00:00Z',
  correction_count: 1,
  latest_correction_id: '66666666-6666-6666-6666-666666666666',
  allowed_actions: ['copy', 'correct'],
}

const communicationDetail = {
  ...communicationSummary,
  template_version_id: '77777777-7777-7777-7777-777777777777',
  root_record_id: null,
  corrects_record_id: null,
  correction_sequence: 0,
  correction_reason: null,
  recipient_type: 'phone',
  body_snapshot: '你好，Offer 已审批通过，请查看候选人门户。',
  is_historical: false,
  historical_note: null,
  created_by_id: '88888888-8888-8888-8888-888888888888',
  created_by_username: 'recruiter',
  created_by_display_name: '招聘专员',
  created_at: '2026-08-02T08:01:00Z',
  corrections: [
    {
      ...communicationSummary,
      id: '66666666-6666-6666-6666-666666666666',
      record_kind: 'correction',
      root_record_id: '11111111-1111-1111-1111-111111111111',
      corrects_record_id: '11111111-1111-1111-1111-111111111111',
      correction_sequence: 1,
      correction_reason: '修正文案说明',
      template_version_id: '77777777-7777-7777-7777-777777777777',
      recipient_type: 'phone',
      body_snapshot: '修正后的 Offer 通知。',
      is_historical: false,
      historical_note: null,
      created_by_id: '88888888-8888-8888-8888-888888888888',
      created_by_username: 'recruiter',
      created_by_display_name: '招聘专员',
      created_at: '2026-08-02T08:05:00Z',
      sent_at: '2026-08-02T08:05:00Z',
      corrections: [],
    },
  ],
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/communications']}>
        <Routes>
          <Route path="/communications" element={<CommunicationRecordsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return queryClient
}

describe('CommunicationRecordsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('展示沟通留痕列表、详情和筛选请求', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      if (path.startsWith('/api/communications?')) {
        return jsonResponse({
          items: [communicationSummary],
          total: 1,
          limit: 20,
          offset: 0,
        })
      }
      if (path === '/api/communications/11111111-1111-1111-1111-111111111111') {
        return jsonResponse(communicationDetail)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByRole('heading', { name: '沟通留痕' })).toBeInTheDocument()
    expect(await screen.findByText('张三')).toBeInTheDocument()
    expect(screen.getByText('Offer 通知')).toBeInTheDocument()
    expect(screen.getByText('138****0000')).toBeInTheDocument()
    expect(screen.getByText('已更正 1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /详情/ }))
    expect(await screen.findByText('沟通快照')).toBeInTheDocument()
    expect(await screen.findByText('你好，Offer 已审批通过，请查看候选人门户。')).toBeInTheDocument()
    expect(await screen.findByText('修正文案说明')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('按业务对象 ID 筛选'), {
      target: { value: '55555555-5555-5555-5555-555555555555' },
    })
    fireEvent.change(screen.getByLabelText('按应聘记录 ID 筛选'), {
      target: { value: '22222222-2222-2222-2222-222222222222' },
    })
    fireEvent.click(screen.getByRole('button', { name: /查\s*询/ }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/communications?context_id=55555555-5555-5555-5555-555555555555&application_id=22222222-2222-2222-2222-222222222222&limit=20&offset=0',
        expect.any(Object),
      ),
    )
  })
})
