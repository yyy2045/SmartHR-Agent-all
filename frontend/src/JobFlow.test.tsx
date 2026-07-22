import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { CriteriaVersion, JobDetail } from './api/client'

const user = {
  id: '03f8ba31-0a83-4466-bc4c-143bd3279680',
  username: 'recruiter',
  display_name: '招聘专员',
}

const timestamp = '2026-07-22T12:00:00Z'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('job and criteria flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
  })

  it('支持创建职位、编辑草稿并确认不可变标准版本', async () => {
    let job: JobDetail | null = null
    let versions: CriteriaVersion[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'

      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs' && method === 'GET') return jsonResponse(job ? [job] : [])
      if (path === '/api/jobs' && method === 'POST') {
        const payload = JSON.parse(init?.body as string) as {
          title: string
          department: string
          original_jd: string
        }
        job = {
          id: 'job-1',
          ...payload,
          status: 'active',
          archived_at: null,
          created_at: timestamp,
          updated_at: timestamp,
          criteria_versions: versions,
        }
        return jsonResponse(job, 201)
      }
      if (path === '/api/jobs/job-1' && method === 'GET') {
        return jsonResponse({ ...job, criteria_versions: versions })
      }
      if (path === '/api/jobs/job-1/criteria/versions' && method === 'POST') {
        const payload = JSON.parse(init?.body as string) as { source_version_id: string | null }
        const source = versions.find((item) => item.id === payload.source_version_id)
        const versionNumber = versions.length + 1
        const version: CriteriaVersion = {
          id: `version-${versionNumber}`,
          job_id: 'job-1',
          version_number: versionNumber,
          status: 'draft',
          pass_threshold: source?.pass_threshold ?? 60,
          source_version_id: source?.id ?? null,
          confirmed_by_id: null,
          confirmed_at: null,
          created_at: timestamp,
          updated_at: timestamp,
          hard_requirements: source?.hard_requirements.map((item) => ({ ...item })) ?? [],
          scoring_dimensions: source?.scoring_dimensions.map((item) => ({ ...item })) ?? [],
        }
        versions = [...versions, version]
        return jsonResponse(version, 201)
      }
      if (path === '/api/jobs/job-1/criteria/versions/version-1' && method === 'PUT') {
        const payload = JSON.parse(init?.body as string) as {
          pass_threshold: number
          hard_requirements: CriteriaVersion['hard_requirements']
          scoring_dimensions: CriteriaVersion['scoring_dimensions']
        }
        versions = [{ ...versions[0], ...payload }]
        return jsonResponse(versions[0])
      }
      if (
        path === '/api/jobs/job-1/criteria/versions/version-1/confirm' &&
        method === 'POST'
      ) {
        versions = [
          {
            ...versions[0],
            status: 'confirmed',
            confirmed_by_id: user.id,
            confirmed_at: timestamp,
          },
        ]
        return jsonResponse(versions[0])
      }
      return jsonResponse({ detail: 'not found' }, 404)
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

    expect(await screen.findByText('暂无进行中的职位')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /创建第一个职位/ }))
    expect(await screen.findByRole('heading', { name: '新建职位' })).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('职位名称'), { target: { value: '高级后端工程师' } })
    fireEvent.change(screen.getByLabelText('所属部门'), { target: { value: '研发中心' } })
    fireEvent.change(screen.getByLabelText('原始 JD'), {
      target: { value: '负责核心服务设计与开发。' },
    })
    fireEvent.click(screen.getByRole('button', { name: /创建并配置标准/ }))

    expect(await screen.findByText('尚未建立筛选标准')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /创建人工筛选标准/ }))

    expect(await screen.findByRole('heading', { name: '标准版本 V1' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /添加评分维度/ }))
    fireEvent.change(screen.getByLabelText('维度名称'), { target: { value: '专业能力' } })
    fireEvent.change(screen.getByLabelText('权重'), { target: { value: '100' } })
    fireEvent.click(screen.getByRole('button', { name: /确认标准/ }))
    fireEvent.click(await screen.findByRole('button', { name: '确认并锁定' }))

    expect(await screen.findByText('已确认版本不可修改')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /基于此版本新建/ }))
    expect(await screen.findByRole('heading', { name: '标准版本 V2' })).toBeInTheDocument()
    expect(screen.getByText('草稿可继续编辑')).toBeInTheDocument()
    expect(screen.getByText('当前权重 100%')).toBeInTheDocument()
    await waitFor(() => {
      expect(versions[0].status).toBe('confirmed')
      expect(versions[0].scoring_dimensions[0].weight_percent).toBe(100)
    })
  })
})
