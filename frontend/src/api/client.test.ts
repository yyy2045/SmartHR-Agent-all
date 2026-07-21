import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchLiveHealth } from './client'

describe('fetchLiveHealth', () => {
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
    expect(fetchMock).toHaveBeenCalledWith('/api/health/live', {
      credentials: 'include',
    })
  })

  it('在后端不可用时抛出可读错误', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 503 })))

    await expect(fetchLiveHealth()).rejects.toThrow('后端服务暂不可用')
  })
})
