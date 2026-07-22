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

export type JobStatus = 'active' | 'archived'
export type CriteriaStatus = 'draft' | 'confirmed'
export type HardRequirementType =
  | 'min_experience_years'
  | 'min_education'
  | 'required_certification'
  | 'language_level'
  | 'other'

export interface JobInput {
  title: string
  department: string
  original_jd: string
}

export interface JobRecord extends JobInput {
  id: string
  status: JobStatus
  archived_at: string | null
  created_at: string
  updated_at: string
}

export interface HardRequirementInput {
  requirement_type: HardRequirementType
  title: string
  description: string
  expected_value: string
  auto_reject: boolean
  sort_order: number
}

export interface HardRequirement extends HardRequirementInput {
  id: string
}

export interface ScoringDimensionInput {
  name: string
  description: string
  weight_percent: number
  sort_order: number
}

export interface ScoringDimension extends ScoringDimensionInput {
  id: string
}

export interface CriteriaVersion {
  id: string
  job_id: string
  version_number: number
  status: CriteriaStatus
  pass_threshold: number
  source_version_id: string | null
  confirmed_by_id: string | null
  confirmed_at: string | null
  created_at: string
  updated_at: string
  hard_requirements: HardRequirement[]
  scoring_dimensions: ScoringDimension[]
}

export interface CriteriaDraftInput {
  pass_threshold: number
  hard_requirements: HardRequirementInput[]
  scoring_dimensions: ScoringDimensionInput[]
}

export interface JobDetail extends JobRecord {
  criteria_versions: CriteriaVersion[]
}

export const AUTH_UNAUTHORIZED_EVENT = 'smarthr:auth-unauthorized'

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
    if (
      response.status === 401 &&
      path !== '/api/auth/me' &&
      path !== '/api/auth/login'
    ) {
      window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT))
    }
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

export function fetchJobs(includeArchived = false): Promise<JobRecord[]> {
  const query = includeArchived ? '?include_archived=true' : ''
  return apiRequest(`/api/jobs${query}`, {}, '无法读取职位列表')
}

export function fetchJob(jobId: string): Promise<JobDetail> {
  return apiRequest(`/api/jobs/${jobId}`, {}, '无法读取职位详情')
}

export function createJob(payload: JobInput): Promise<JobRecord> {
  return apiRequest(
    '/api/jobs',
    { method: 'POST', body: JSON.stringify(payload) },
    '创建职位失败',
  )
}

export function updateJob(jobId: string, payload: Partial<JobInput>): Promise<JobRecord> {
  return apiRequest(
    `/api/jobs/${jobId}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
    '保存职位失败',
  )
}

export function archiveJob(jobId: string): Promise<JobRecord> {
  return apiRequest(`/api/jobs/${jobId}/archive`, { method: 'POST' }, '归档职位失败')
}

export function createCriteriaVersion(
  jobId: string,
  sourceVersionId?: string,
): Promise<CriteriaVersion> {
  return apiRequest(
    `/api/jobs/${jobId}/criteria/versions`,
    {
      method: 'POST',
      body: JSON.stringify({ source_version_id: sourceVersionId ?? null }),
    },
    '创建筛选标准版本失败',
  )
}

export function updateCriteriaDraft(
  jobId: string,
  versionId: string,
  payload: CriteriaDraftInput,
): Promise<CriteriaVersion> {
  return apiRequest(
    `/api/jobs/${jobId}/criteria/versions/${versionId}`,
    { method: 'PUT', body: JSON.stringify(payload) },
    '保存筛选标准失败',
  )
}

export function confirmCriteriaVersion(
  jobId: string,
  versionId: string,
): Promise<CriteriaVersion> {
  return apiRequest(
    `/api/jobs/${jobId}/criteria/versions/${versionId}/confirm`,
    { method: 'POST' },
    '确认筛选标准失败',
  )
}
