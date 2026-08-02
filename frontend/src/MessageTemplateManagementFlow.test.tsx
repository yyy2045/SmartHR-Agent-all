import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { MessageTemplateManagementPage } from './pages/MessageTemplateManagementPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const templateSummary = {
  id: '11111111-1111-1111-1111-111111111111',
  system_key: 'interview_invitation_default',
  template_type: 'interview_invitation',
  name: '默认面试通知',
  status: 'active',
  current_version_number: 1,
  resource_version: 2,
  current_subject: '面试通知',
  updated_at: '2026-08-02T08:00:00Z',
  allowed_actions: ['create_version', 'deactivate'],
}

const templateDetail = {
  ...templateSummary,
  created_by_id: '22222222-2222-2222-2222-222222222222',
  created_by_username: 'admin',
  created_by_display_name: '管理员',
  created_at: '2026-08-02T07:00:00Z',
  current_version: {
    id: '33333333-3333-3333-3333-333333333333',
    version_number: 1,
    source_version_id: null,
    subject: '面试通知',
    body: '旧正文 {{candidate_name}}',
    variables: ['candidate_name'],
    created_by_id: '22222222-2222-2222-2222-222222222222',
    created_by_username: 'admin',
    created_by_display_name: '管理员',
    created_at: '2026-08-02T07:00:00Z',
  },
  versions: [
    {
      id: '33333333-3333-3333-3333-333333333333',
      version_number: 1,
      source_version_id: null,
      subject: '面试通知',
      body: '旧正文 {{candidate_name}}',
      variables: ['candidate_name'],
      created_by_id: '22222222-2222-2222-2222-222222222222',
      created_by_username: 'admin',
      created_by_display_name: '管理员',
      created_at: '2026-08-02T07:00:00Z',
    },
  ],
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/message-templates']}>
        <Routes>
          <Route path="/message-templates" element={<MessageTemplateManagementPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return queryClient
}

describe('MessageTemplateManagementPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('展示模板详情，支持保存新版本和停用模板', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      if (path.startsWith('/api/message-templates?')) {
        return jsonResponse({
          items: [templateSummary],
          total: 1,
          limit: 20,
          offset: 0,
        })
      }
      if (
        path === '/api/message-templates/11111111-1111-1111-1111-111111111111' &&
        (!init?.method || init.method === 'GET')
      ) {
        return jsonResponse(templateDetail)
      }
      if (
        path === '/api/message-templates/11111111-1111-1111-1111-111111111111/versions' &&
        init?.method === 'POST'
      ) {
        return jsonResponse({
          ...templateDetail,
          current_version_number: 2,
          resource_version: 3,
          current_version: {
            ...templateDetail.current_version,
            id: '44444444-4444-4444-4444-444444444444',
            version_number: 2,
            subject: '新版面试通知',
            body: '新版正文 {{candidate_name}}',
          },
        })
      }
      if (
        path === '/api/message-templates/11111111-1111-1111-1111-111111111111/deactivate' &&
        init?.method === 'POST'
      ) {
        return jsonResponse({
          ...templateDetail,
          status: 'inactive',
          allowed_actions: ['create_version', 'activate'],
        })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByRole('heading', { name: '沟通模板' })).toBeInTheDocument()
    expect(await screen.findByText('默认面试通知')).toBeInTheDocument()
    expect(screen.getAllByText('面试通知').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: /详情/ }))
    expect(await screen.findByText('当前版本内容')).toBeInTheDocument()
    expect(await screen.findByText('旧正文 {{candidate_name}}')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /新版本/ }))
    expect(await screen.findByText('模板名称和类型保持不变，本次修改会生成新的历史版本。')).toBeInTheDocument()
    fireEvent.change(screen.getByDisplayValue('面试通知'), {
      target: { value: '新版面试通知' },
    })
    fireEvent.change(screen.getByDisplayValue('旧正文 {{candidate_name}}'), {
      target: { value: '新版正文 {{candidate_name}}' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^OK$/ }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/message-templates/11111111-1111-1111-1111-111111111111/versions',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    const versionCall = fetchMock.mock.calls.find(
      ([path]) =>
        path === '/api/message-templates/11111111-1111-1111-1111-111111111111/versions',
    )
    expect(JSON.parse(versionCall?.[1]?.body as string)).toMatchObject({
      expected_version: 2,
      subject: '新版面试通知',
      body: '新版正文 {{candidate_name}}',
      variables: ['candidate_name'],
    })

    const row = screen
      .getAllByText('默认面试通知')
      .find((element) => element.closest('tbody'))
      ?.closest('tr')
    expect(row).not.toBeNull()
    fireEvent.click(within(row as HTMLTableRowElement).getByRole('button', { name: /停用/ }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/message-templates/11111111-1111-1111-1111-111111111111/deactivate',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
  })
})
