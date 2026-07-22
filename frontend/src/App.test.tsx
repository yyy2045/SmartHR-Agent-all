import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

const user = {
  id: '03f8ba31-0a83-4466-bc4c-143bd3279680',
  username: 'recruiter',
  display_name: '招聘专员',
}

describe('authentication flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('将未登录用户引导到登录页，并支持登录和退出', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      if (path === '/api/auth/me') {
        return new Response(JSON.stringify({ detail: '请先登录' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (path === '/api/auth/login' && init?.method === 'POST') {
        return new Response(JSON.stringify(user), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (path === '/api/auth/logout' && init?.method === 'POST') {
        return new Response(null, { status: 204 })
      }
      if (path === '/api/health/live') {
        return new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (path === '/api/jobs') {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response(null, { status: 404 })
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/')

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: '登录' })).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'recruiter' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'example-password' } })
    fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }))

    expect(await screen.findByRole('heading', { name: '职位筛选' })).toBeInTheDocument()
    expect(screen.getByText('招聘专员')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
    await waitFor(() => expect(queryClient.getQueryData(['auth', 'current-user'])).toBeNull())
    await waitFor(() => expect(window.location.pathname).toBe('/login'))
    expect(await screen.findByRole('heading', { name: '登录' })).toBeInTheDocument()
  })
})
