import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { CriteriaVersion, JobDetail } from './api/client'

const user = {
  id: '03f8ba31-0a83-4466-bc4c-143bd3279680',
  username: 'recruiter',
  display_name: '招聘专员',
  is_active: true,
  must_change_password: false,
  roles: ['recruiter'],
}
const manager = {
  ...user,
  id: 'manager-1',
  username: 'manager',
  display_name: '用人经理',
  roles: ['hiring_manager'],
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

  it('用人经理只能查看筛选标准草稿', async () => {
    const draft: CriteriaVersion = {
      id: 'version-1',
      job_id: 'job-1',
      version_number: 1,
      status: 'draft',
      pass_threshold: 60,
      source_version_id: null,
      confirmed_by_id: null,
      confirmed_at: null,
      created_at: timestamp,
      updated_at: timestamp,
      hard_requirements: [],
      scoring_dimensions: [],
    }
    const managedJob: JobDetail = {
      id: 'job-1',
      recruiter_id: user.id,
      hiring_manager_id: manager.id,
      recruitment_request_id: null,
      title: '平台工程师',
      department: '研发中心',
      original_jd: '负责平台工程建设。',
      status: 'active',
      archived_at: null,
      created_at: timestamp,
      updated_at: timestamp,
      criteria_versions: [draft],
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = input.toString()
      if (path === '/api/auth/me') return jsonResponse(manager)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-1') return jsonResponse(managedJob)
      return jsonResponse({ detail: 'not found' }, 404)
    }))
    window.history.replaceState({}, '', '/jobs/job-1/criteria')
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )

    expect(await screen.findByText('当前角色可查看筛选标准，但不能修改')).toBeInTheDocument()
    expect(screen.getByLabelText('语义匹配通过线')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'AI 生成草稿' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '保存草稿' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '确认标准' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '编辑职位信息' })).not.toBeInTheDocument()
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
          recruiter_id: user.id,
          hiring_manager_id: null,
          recruitment_request_id: null,
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
    window.history.replaceState({}, '', '/jobs')

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
    fireEvent.click(screen.getByRole('button', { name: /创建筛选标准草稿/ }))

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

  it('将 AI 结构化结果填入表单但不会自动保存或确认', async () => {
    const version: CriteriaVersion = {
      id: 'version-ai-1',
      job_id: 'job-ai',
      version_number: 1,
      status: 'draft',
      pass_threshold: 60,
      source_version_id: null,
      confirmed_by_id: null,
      confirmed_at: null,
      created_at: timestamp,
      updated_at: timestamp,
      hard_requirements: [],
      scoring_dimensions: [],
    }
    const job: JobDetail = {
      id: 'job-ai',
      recruiter_id: user.id,
      hiring_manager_id: null,
      recruitment_request_id: null,
      title: '后端工程师',
      department: '研发中心',
      original_jd: '负责 Python 服务开发。',
      status: 'active',
      archived_at: null,
      created_at: timestamp,
      updated_at: timestamp,
      criteria_versions: [version],
    }
    const aiDraft = {
      suggested_title: '高级后端工程师',
      summary: '负责核心服务设计、研发与稳定性建设。',
      pass_threshold: 65,
      hard_requirements: [
        {
          requirement_type: 'min_experience_years' as const,
          title: '相关经验',
          description: '后端开发经验',
          expected_value: '3 年',
          auto_reject: true,
          sort_order: 0,
        },
      ],
      scoring_dimensions: [
        {
          name: '系统设计',
          description: '关注可扩展架构',
          weight_percent: 60,
          sort_order: 0,
        },
        {
          name: '工程质量',
          description: '关注测试和稳定性',
          weight_percent: 40,
          sort_order: 1,
        },
      ],
    }
    let savedPayload: unknown = null
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString()
      const method = init?.method ?? 'GET'
      if (path === '/api/auth/me') return jsonResponse(user)
      if (path === '/api/health/live') return jsonResponse({ status: 'ok' })
      if (path === '/api/jobs/job-ai') return jsonResponse(job)
      if (path === '/api/jobs/job-ai/criteria/ai-draft' && method === 'POST') {
        return jsonResponse(aiDraft)
      }
      if (
        path === '/api/jobs/job-ai/criteria/versions/version-ai-1' &&
        method === 'PUT'
      ) {
        savedPayload = JSON.parse(init?.body as string)
        return jsonResponse({ ...version, ...(savedPayload as object) })
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/jobs/job-ai/criteria')
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: '标准版本 V1' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /AI 生成草稿/ }))
    fireEvent.click(await screen.findByRole('button', { name: '生成并替换' }))

    expect(await screen.findByText('建议职位名称：高级后端工程师')).toBeInTheDocument()
    expect(screen.getByText('负责核心服务设计、研发与稳定性建设。')).toBeInTheDocument()
    expect(screen.getByDisplayValue('相关经验')).toBeInTheDocument()
    expect(screen.getByDisplayValue('3 年')).toBeInTheDocument()
    expect(screen.getByDisplayValue('系统设计')).toBeInTheDocument()
    expect(screen.getByDisplayValue('工程质量')).toBeInTheDocument()
    expect(screen.getByText('当前权重 100%')).toBeInTheDocument()
    expect(savedPayload).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /保存草稿/ }))
    await waitFor(() => expect(savedPayload).not.toBeNull())
    expect(savedPayload).toMatchObject({
      pass_threshold: 65,
      hard_requirements: [{ title: '相关经验', auto_reject: true }],
      scoring_dimensions: [
        { name: '系统设计', weight_percent: 60 },
        { name: '工程质量', weight_percent: 40 },
      ],
    })
  })
})
