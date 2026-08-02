import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

import { NotificationCenterPage } from './pages/NotificationCenterPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>
}

function renderPage(path = '/notifications') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/notifications" element={<NotificationCenterPage />} />
          <Route path="/offers" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return queryClient
}

describe('NotificationCenterPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('展示未读消息、支持标记已读并跳转业务页面', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      if (path.startsWith('/api/notifications?')) {
        return jsonResponse({
          items: [
            {
              id: 'notification-1',
              notification_type: 'offer_approved',
              title: 'Offer 已批准',
              summary: '高级后端工程师的 Offer 已批准',
              resource_type: 'offer',
              resource_id: 'offer-1',
              route_path: '/offers?selected=offer-1',
              read_at: null,
              created_at: '2026-08-02T08:00:00Z',
            },
          ],
          total: 1,
          unread_count: 1,
          limit: 10,
          offset: 0,
        })
      }
      if (path === '/api/notifications/notification-1/read' && init?.method === 'POST') {
        return jsonResponse({
          id: 'notification-1',
          read_at: '2026-08-02T08:01:00Z',
        })
      }
      if (path === '/api/notifications/read-all' && init?.method === 'POST') {
        return jsonResponse({
          updated_count: 1,
          read_at: '2026-08-02T08:01:00Z',
        })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    expect(await screen.findByRole('heading', { name: '消息中心' })).toBeInTheDocument()
    expect(await screen.findByText('高级后端工程师的 Offer 已批准')).toBeInTheDocument()
    expect(await screen.findByText('未读 1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /^标记已读$/ }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/notifications/notification-1/read',
        expect.objectContaining({ method: 'POST' }),
      ),
    )

    fireEvent.click(screen.getByRole('button', { name: /查看/ }))
    expect(await screen.findByTestId('location')).toHaveTextContent('/offers?selected=offer-1')
  })

  it('支持未读筛选和全部标记已读', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      if (path.startsWith('/api/notifications?')) {
        return jsonResponse({
          items: [],
          total: 0,
          unread_count: 2,
          limit: 10,
          offset: 0,
        })
      }
      if (path === '/api/notifications/read-all' && init?.method === 'POST') {
        return jsonResponse({
          updated_count: 2,
          read_at: '2026-08-02T08:01:00Z',
        })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage('/notifications?status=unread')

    expect(await screen.findByText('当前筛选条件下没有消息')).toBeInTheDocument()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/notifications?status=unread&limit=10&offset=0')

    fireEvent.click(screen.getByRole('button', { name: /全部标记已读/ }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/notifications/read-all',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
  })
})
