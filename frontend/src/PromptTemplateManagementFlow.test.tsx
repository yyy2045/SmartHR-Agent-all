import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PromptTemplateManagementPage } from './pages/PromptTemplateManagementPage'

const template = {
  id: 'template-1',
  scenario: 'resume_analysis',
  name: '简历评分 Prompt',
  description: '根据职位标准分析简历',
  status: 'active',
  current_version_number: 1,
  resource_version: 2,
  created_by_id: 'admin-1',
  created_by_username: 'administrator',
  created_by_display_name: '管理员',
  created_at: '2026-08-04T12:00:00Z',
  updated_at: '2026-08-04T12:30:00Z',
  versions: [
    {
      id: 'version-1',
      template_id: 'template-1',
      version_number: 1,
      status: 'published',
      source_version_id: null,
      change_note: '初始化模板',
      system_prompt: '你是企业招聘的人岗匹配助手。',
      user_prompt_template: '职位标准：{{criteria}}\n简历：{{resume}}',
      variables: ['criteria', 'resume'],
      output_schema: { type: 'object' },
      model_parameters: { temperature: 0 },
      created_by_id: 'admin-1',
      created_by_username: 'administrator',
      created_by_display_name: '管理员',
      published_by_id: 'admin-1',
      published_by_username: 'administrator',
      published_by_display_name: '管理员',
      published_at: '2026-08-04T12:10:00Z',
      created_at: '2026-08-04T12:00:00Z',
    },
    {
      id: 'version-2',
      template_id: 'template-1',
      version_number: 2,
      status: 'draft',
      source_version_id: 'version-1',
      change_note: '强化证据要求',
      system_prompt: '你是企业招聘的人岗匹配助手，必须引用证据。',
      user_prompt_template: '职位标准：{{criteria}}\n简历：{{resume}}',
      variables: ['criteria', 'resume'],
      output_schema: { type: 'object', required: ['summary'] },
      model_parameters: { temperature: 0 },
      created_by_id: 'admin-1',
      created_by_username: 'administrator',
      created_by_display_name: '管理员',
      published_by_id: null,
      published_by_username: null,
      published_by_display_name: null,
      published_at: null,
      created_at: '2026-08-04T12:20:00Z',
    },
  ],
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <PromptTemplateManagementPage />
    </QueryClientProvider>,
  )
}

describe('PromptTemplateManagementPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('展示 Prompt 模板历史并发布草稿版本', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(input.toString(), 'http://localhost')
      if (url.pathname === '/api/prompt-templates' && !init?.method) {
        return json({ items: [template] })
      }
      if (url.pathname === '/api/prompt-templates/template-1' && !init?.method) {
        return json(template)
      }
      if (url.pathname === '/api/prompt-templates/template-1/publish') {
        return json({
          ...template,
          current_version_number: 2,
          resource_version: 3,
          versions: [
            { ...template.versions[0], status: 'retired' },
            { ...template.versions[1], status: 'published', published_at: '2026-08-04T13:00:00Z' },
          ],
        })
      }
      return json({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByRole('heading', { name: 'PromptOps' })).toBeInTheDocument()
    expect(await screen.findByText('简历评分 Prompt')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /详情/ }))

    expect(await screen.findByText('版本历史')).toBeInTheDocument()
    expect(screen.getByText('强化证据要求')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /发布/ }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/prompt-templates/template-1/publish',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    const body = JSON.parse(
      fetchMock.mock.calls.find((call) =>
        call[0].toString().endsWith('/api/prompt-templates/template-1/publish'),
      )?.[1]?.body as string,
    )
    expect(body).toMatchObject({
      version_id: 'version-2',
      expected_version: 2,
    })
  })

  it('保存 Prompt 模板的新版本草稿', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(input.toString(), 'http://localhost')
      if (url.pathname === '/api/prompt-templates' && !init?.method) {
        return json({ items: [template] })
      }
      if (url.pathname === '/api/prompt-templates' && init?.method === 'POST') {
        return json({ ...template, id: 'template-created' }, 201)
      }
      if (url.pathname === '/api/prompt-templates/template-1/versions') {
        return json({
          ...template,
          resource_version: 3,
          versions: [...template.versions, { ...template.versions[1], id: 'version-3', version_number: 3 }],
        })
      }
      return json(template)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    await screen.findByText('简历评分 Prompt')
    fireEvent.click(screen.getByRole('button', { name: /新版本/ }))
    const dialog = await screen.findByRole('dialog', { name: /保存 简历评分 Prompt 的新版本/ })
    fireEvent.change(within(dialog).getByLabelText('版本说明'), {
      target: { value: '补充风险提示' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: /保存新版本草稿/ }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/prompt-templates/template-1/versions',
        expect.objectContaining({ method: 'POST' }),
      ),
    )

  })

  it('创建 Prompt 模板草稿', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(input.toString(), 'http://localhost')
      if (url.pathname === '/api/prompt-templates' && !init?.method) {
        return json({ items: [template] })
      }
      if (url.pathname === '/api/prompt-templates' && init?.method === 'POST') {
        return json({ ...template, id: 'template-created' }, 201)
      }
      if (url.pathname === '/api/prompt-templates/template-created') {
        return json({ ...template, id: 'template-created' })
      }
      return json(template)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    await screen.findByText('简历评分 Prompt')
    fireEvent.click(screen.getByRole('button', { name: /创建 Prompt/ }))
    const createDialog = await screen.findByRole('dialog', { name: /创建 Prompt 模板/ })
    fireEvent.change(within(createDialog).getByLabelText('模板名称'), {
      target: { value: 'JD 结构化 Prompt' },
    })
    fireEvent.change(within(createDialog).getByLabelText('版本说明'), { target: { value: '初始化' } })
    fireEvent.change(within(createDialog).getByLabelText('System Prompt'), {
      target: { value: '你是 JD 结构化助手' },
    })
    fireEvent.change(within(createDialog).getByLabelText('User Prompt 模板'), {
      target: { value: 'JD：{{jd}}' },
    })
    fireEvent.change(within(createDialog).getByLabelText('变量，一行一个'), { target: { value: 'jd' } })
    fireEvent.click(within(createDialog).getByRole('button', { name: /保存草稿/ }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/prompt-templates',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
  })
})
