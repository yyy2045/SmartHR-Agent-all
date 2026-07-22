import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  AUTH_UNAUTHORIZED_EVENT,
  createScreeningBatch,
  fetchCurrentUser,
  fetchJobs,
  fetchLiveHealth,
  login,
  logout,
} from './client'

describe('API client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('返回后端健康状态', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchLiveHealth()).resolves.toEqual({ status: 'ok' })
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/health/live')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: 'include' })
  })

  it('将未登录状态转换为空用户', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: '请先登录' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(fetchCurrentUser()).resolves.toBeNull()
  })

  it('提交登录凭据并返回用户', async () => {
    const user = { id: 'user-1', username: 'recruiter', display_name: '招聘专员' }
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(user), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(login({ username: 'recruiter', password: 'example-password' })).resolves.toEqual(
      user,
    )
    const request = fetchMock.mock.calls[0]
    expect(request[0]).toBe('/api/auth/login')
    expect(request[1]).toMatchObject({ method: 'POST', credentials: 'include' })
    expect(request[1]?.body).toBe(
      JSON.stringify({ username: 'recruiter', password: 'example-password' }),
    )
  })

  it('显示后端返回的登录错误', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: '用户名或密码错误' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(login({ username: 'recruiter', password: 'wrong-password' })).rejects.toEqual(
      new ApiError(401, '用户名或密码错误'),
    )
  })

  it('退出登录时接受 204 响应', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))

    await expect(logout()).resolves.toBeUndefined()
  })

  it('业务请求会话失效时通知认证状态清理', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: '请先登录' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    const unauthorizedListener = vi.fn()
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, unauthorizedListener)

    await expect(fetchJobs()).rejects.toEqual(new ApiError(401, '请先登录'))
    expect(unauthorizedListener).toHaveBeenCalledOnce()

    window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, unauthorizedListener)
  })

  it('使用浏览器生成的 multipart 边界上传简历批次', async () => {
    const batch = {
      id: 'batch-1',
      job_id: 'job-1',
      criteria_version_id: 'version-1',
      criteria_version_number: 1,
      name: '测试批次',
      status: 'ready',
      total_count: 1,
      success_count: 1,
      failed_count: 0,
      processing_count: 0,
      created_at: '2026-07-22T12:00:00Z',
      updated_at: '2026-07-22T12:00:00Z',
      documents: [],
    }
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(batch), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['resume'], 'resume.pdf', { type: 'application/pdf' })

    await expect(
      createScreeningBatch('job-1', 'version-1', [file], '测试批次'),
    ).resolves.toEqual(batch)

    const request = fetchMock.mock.calls[0]
    expect(request[0]).toBe('/api/jobs/job-1/batches')
    expect(request[1]?.body).toBeInstanceOf(FormData)
    expect(new Headers(request[1]?.headers).has('Content-Type')).toBe(false)
    const body = request[1]?.body as FormData
    expect(body.get('criteria_version_id')).toBe('version-1')
    expect(body.getAll('files')).toHaveLength(1)
  })
})
