export interface HealthResponse {
  status: string
}

export interface AuthUser {
  id: string
  username: string
  display_name: string
}

export interface LoginCredentials {
  username: string
  password: string
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  fallbackMessage = '请求失败',
): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, {
    ...init,
    headers,
    credentials: 'include',
  })

  if (!response.ok) {
    let message = fallbackMessage
    try {
      const body = (await response.json()) as { detail?: string }
      message = body.detail || fallbackMessage
    } catch {
      // The fallback remains when the server does not return JSON.
    }
    throw new ApiError(response.status, message)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export function fetchLiveHealth(): Promise<HealthResponse> {
  return apiRequest('/api/health/live', {}, '后端服务暂不可用')
}

export async function fetchCurrentUser(): Promise<AuthUser | null> {
  try {
    return await apiRequest<AuthUser>('/api/auth/me', {}, '无法读取登录状态')
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null
    }
    throw error
  }
}

export function login(credentials: LoginCredentials): Promise<AuthUser> {
  return apiRequest<AuthUser>(
    '/api/auth/login',
    {
      method: 'POST',
      body: JSON.stringify(credentials),
    },
    '登录失败，请稍后重试',
  )
}

export function logout(): Promise<void> {
  return apiRequest<void>(
    '/api/auth/logout',
    {
      method: 'POST',
    },
    '退出失败，请稍后重试',
  )
}
