export interface HealthResponse {
  status: string
}

export async function fetchLiveHealth(): Promise<HealthResponse> {
  const response = await fetch('/api/health/live', {
    credentials: 'include',
  })

  if (!response.ok) {
    throw new Error('后端服务暂不可用')
  }

  return response.json() as Promise<HealthResponse>
}
