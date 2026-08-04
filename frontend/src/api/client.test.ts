import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  AUTH_UNAUTHORIZED_EVENT,
  activateMessageTemplate,
  askCandidateAgent,
  createCandidateAgentSession,
  createOfferPortalLink,
  createMessageTemplate,
  createMessageTemplateVersion,
  createPromptTemplate,
  createPromptTemplateVersion,
  createRecruitmentKnowledgeManual,
  createScreeningBatch,
  deactivateMessageTemplate,
  fetchCandidateAgentSession,
  fetchCandidateAgentSessions,
  fetchAIObservabilityCalls,
  fetchAIObservabilitySummary,
  fetchAIObservabilityTasks,
  fetchOfferPortalStatus,
  fetchCurrentUser,
  fetchCommunicationRecord,
  fetchCommunicationRecords,
  fetchInternalNotificationUnreadCount,
  fetchMessageTemplate,
  fetchMessageTemplates,
  fetchPromptTemplate,
  fetchPromptTemplates,
  fetchRecruitmentKnowledgeBases,
  fetchInternalNotifications,
  fetchJobs,
  fetchLiveHealth,
  fetchWorkbenchItems,
  fetchWorkbenchSummary,
  fetchResumeDocumentDetail,
  generateJDAIDraft,
  login,
  logout,
  markAllInternalNotificationsRead,
  markInternalNotificationRead,
  previewCommunication,
  publishPromptTemplateVersion,
  retrieveRecruitmentKnowledge,
  recordCommunicationCopyAudit,
  respondToOfferPortal,
  retryResumeParsing,
  uploadRecruitmentKnowledgeDocument,
  updateCandidatePhone,
  verifyOfferPortal,
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

  it('按工作台筛选契约生成摘要和分页查询', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await fetchWorkbenchSummary()
    await fetchWorkbenchItems({
      section: 'action_required',
      itemType: 'offer_approval',
      priority: 'high',
      jobId: 'job-1',
      page: 2,
      pageSize: 6,
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/workbench/summary')
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/workbench/items?section=action_required&item_type=offer_approval&priority=high&job_id=job-1&page=2&page_size=6',
    )
  })
  it('按消息中心筛选契约生成查询和已读请求', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ items: [], total: 0, unread_count: 0, limit: 10, offset: 10 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await fetchInternalNotifications({
      status: 'unread',
      notificationType: 'offer_approved',
      limit: 10,
      offset: 10,
    })
    await fetchInternalNotificationUnreadCount()
    await markInternalNotificationRead('notification-1')
    await markAllInternalNotificationsRead()

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/notifications?status=unread&notification_type=offer_approved&limit=10&offset=10',
    )
    expect(fetchMock.mock.calls[1][0]).toBe('/api/notifications/unread-count')
    expect(fetchMock.mock.calls[2][0]).toBe('/api/notifications/notification-1/read')
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: 'POST' })
    expect(fetchMock.mock.calls[3][0]).toBe('/api/notifications/read-all')
    expect(fetchMock.mock.calls[3][1]).toMatchObject({ method: 'POST' })
  })

  it('builds AI observability summary, task and call requests', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ items: [], total: 0, limit: 20, offset: 0 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await fetchAIObservabilitySummary()
    await fetchAIObservabilityTasks({
      status: 'failed',
      scenario: 'resume_analysis',
      limit: 20,
      offset: 40,
    })
    await fetchAIObservabilityCalls({
      status: 'succeeded',
      scenario: 'jd_generation',
      limit: 10,
      offset: 0,
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/ai-observability/summary')
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/ai-observability/tasks?status=failed&scenario=resume_analysis&limit=20&offset=40',
    )
    expect(fetchMock.mock.calls[2][0]).toBe(
      '/api/ai-observability/calls?status=succeeded&scenario=jd_generation&limit=10&offset=0',
    )
  })

  it('builds candidate Agent session and ask requests', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ items: [], exchanges: [], id: 'session-1' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await fetchCandidateAgentSessions('job-1', 'application-1')
    await createCandidateAgentSession('job-1', 'application-1', '风险分析')
    await fetchCandidateAgentSession('job-1', 'application-1', 'session-1')
    await askCandidateAgent(
      'job-1',
      'application-1',
      'session-1',
      '这个候选人的风险是什么？',
      'agent-key-1',
    )

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/jobs/job-1/applications/application-1/candidate-agent/sessions',
    )
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/jobs/job-1/applications/application-1/candidate-agent/sessions',
    )
    expect(JSON.parse(fetchMock.mock.calls[1][1]?.body as string)).toEqual({
      title: '风险分析',
    })
    expect(fetchMock.mock.calls[2][0]).toBe(
      '/api/jobs/job-1/applications/application-1/candidate-agent/sessions/session-1',
    )
    expect(fetchMock.mock.calls[3][0]).toBe(
      '/api/jobs/job-1/applications/application-1/candidate-agent/sessions/session-1/ask',
    )
    expect(JSON.parse(fetchMock.mock.calls[3][1]?.body as string)).toEqual({
      question: '这个候选人的风险是什么？',
      idempotency_key: 'agent-key-1',
    })
  })

  it('builds PromptOps template management requests', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ id: 'template-1', items: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await fetchPromptTemplates()
    await fetchPromptTemplate('template-1')
    await createPromptTemplate({
      scenario: 'resume_analysis',
      name: '简历评分 Prompt',
      description: '用于简历初筛',
      changeNote: '初始化',
      systemPrompt: '你是招聘助手',
      userPromptTemplate: '简历：{{resume}}',
      variables: ['resume'],
      outputSchema: { type: 'object' },
      modelParameters: { temperature: 0 },
      idempotencyKey: 'create-prompt-key',
    })
    await createPromptTemplateVersion('template-1', {
      sourceVersionId: 'version-1',
      changeNote: '补充证据要求',
      systemPrompt: '你是招聘助手，必须引用证据',
      userPromptTemplate: '简历：{{resume}}',
      variables: ['resume'],
      outputSchema: { type: 'object', required: ['summary'] },
      modelParameters: { temperature: 0 },
      idempotencyKey: 'version-prompt-key',
    })
    await publishPromptTemplateVersion('template-1', 'version-2', 3, 'publish-prompt-key')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/prompt-templates')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/prompt-templates/template-1')
    expect(fetchMock.mock.calls[2][0]).toBe('/api/prompt-templates')
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: 'POST' })
    expect(JSON.parse(fetchMock.mock.calls[2][1]?.body as string)).toEqual({
      scenario: 'resume_analysis',
      name: '简历评分 Prompt',
      description: '用于简历初筛',
      change_note: '初始化',
      system_prompt: '你是招聘助手',
      user_prompt_template: '简历：{{resume}}',
      variables: ['resume'],
      output_schema: { type: 'object' },
      model_parameters: { temperature: 0 },
      idempotency_key: 'create-prompt-key',
    })
    expect(fetchMock.mock.calls[3][0]).toBe('/api/prompt-templates/template-1/versions')
    expect(JSON.parse(fetchMock.mock.calls[3][1]?.body as string)).toEqual({
      source_version_id: 'version-1',
      change_note: '补充证据要求',
      system_prompt: '你是招聘助手，必须引用证据',
      user_prompt_template: '简历：{{resume}}',
      variables: ['resume'],
      output_schema: { type: 'object', required: ['summary'] },
      model_parameters: { temperature: 0 },
      idempotency_key: 'version-prompt-key',
    })
    expect(fetchMock.mock.calls[4][0]).toBe('/api/prompt-templates/template-1/publish')
    expect(JSON.parse(fetchMock.mock.calls[4][1]?.body as string)).toEqual({
      version_id: 'version-2',
      expected_version: 3,
      idempotency_key: 'publish-prompt-key',
    })
  })

  it('builds recruitment knowledge RAG requests', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ items: [], citations: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await fetchRecruitmentKnowledgeBases()
    await createRecruitmentKnowledgeManual({
      title: '后端面试评分标准',
      summary: '统一评分口径',
      category: 'interview',
      tags: ['后端', '面试'],
      visibilityScope: 'recruiter_manager',
      changeNote: '初始化',
      rawText: '# 接口设计\n需要说明幂等策略。',
      idempotencyKey: 'knowledge-manual-key',
    })
    await uploadRecruitmentKnowledgeDocument({
      title: 'Offer 沟通话术',
      category: 'communication',
      tags: ['Offer'],
      visibilityScope: 'recruiter_only',
      changeNote: '上传话术',
      file: new File(['hello'], 'offer.md', { type: 'text/markdown' }),
      idempotencyKey: 'knowledge-upload-key',
    })
    await retrieveRecruitmentKnowledge({
      scenario: 'knowledge_preview',
      query: 'Offer 前需要确认什么？',
      category: 'offer',
      tags: ['审批'],
      limit: 3,
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/recruitment-knowledge/bases')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/recruitment-knowledge/documents/manual')
    expect(JSON.parse(fetchMock.mock.calls[1][1]?.body as string)).toEqual({
      knowledge_base_id: null,
      title: '后端面试评分标准',
      summary: '统一评分口径',
      category: 'interview',
      tags: ['后端', '面试'],
      visibility_scope: 'recruiter_manager',
      change_note: '初始化',
      raw_text: '# 接口设计\n需要说明幂等策略。',
      idempotency_key: 'knowledge-manual-key',
    })
    expect(fetchMock.mock.calls[2][0]).toBe('/api/recruitment-knowledge/documents/upload')
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: 'POST' })
    expect(fetchMock.mock.calls[2][1]?.body).toBeInstanceOf(FormData)
    expect(fetchMock.mock.calls[3][0]).toBe('/api/recruitment-knowledge/retrieve')
    expect(JSON.parse(fetchMock.mock.calls[3][1]?.body as string)).toEqual({
      scenario: 'knowledge_preview',
      query: 'Offer 前需要确认什么？',
      category: 'offer',
      tags: ['审批'],
      limit: 3,
    })
  })

  it('builds message template and communication requests', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ items: [], total: 0, limit: 20, offset: 0 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await fetchMessageTemplates({
      status: 'active',
      templateType: 'offer_notification',
      limit: 20,
      offset: 0,
    })
    await fetchMessageTemplate('template-1')
    await previewCommunication({
      templateVersionId: 'template-version-1',
      contextType: 'offer',
      contextId: 'offer-1',
    })
    await recordCommunicationCopyAudit({
      contextType: 'offer',
      contextId: 'offer-1',
      templateVersionId: 'template-version-1',
      subject: 'Offer notice',
      body: 'Offer body',
      idempotencyKey: 'copy-key-1',
    })

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/message-templates?status=active&template_type=offer_notification&limit=20&offset=0',
    )
    expect(fetchMock.mock.calls[1][0]).toBe('/api/message-templates/template-1')
    expect(fetchMock.mock.calls[2][0]).toBe('/api/communications/preview')
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: 'POST' })
    expect(JSON.parse(fetchMock.mock.calls[2][1]?.body as string)).toEqual({
      template_version_id: 'template-version-1',
      context_type: 'offer',
      context_id: 'offer-1',
      subject_override: null,
      body_override: null,
    })
    expect(fetchMock.mock.calls[3][0]).toBe('/api/communications/copy-audit')
    expect(fetchMock.mock.calls[3][1]).toMatchObject({ method: 'POST' })
    expect(JSON.parse(fetchMock.mock.calls[3][1]?.body as string)).toEqual({
      context_type: 'offer',
      context_id: 'offer-1',
      template_version_id: 'template-version-1',
      subject: 'Offer notice',
      body: 'Offer body',
      idempotency_key: 'copy-key-1',
    })
  })

  it('builds message template management requests', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ id: 'template-1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })),
    )
    vi.stubGlobal('fetch', fetchMock)

    await createMessageTemplate({
      templateType: 'interview_invitation',
      name: '默认面试通知',
      subject: '面试通知',
      body: '你好 {{candidate_name}}',
      variables: ['candidate_name'],
      idempotencyKey: 'create-key-1',
    })
    await createMessageTemplateVersion('template-1', {
      expectedVersion: 3,
      subject: '新版面试通知',
      body: '新版正文',
      variables: ['candidate_name', 'interview_time'],
      idempotencyKey: 'version-key-1',
    })
    await deactivateMessageTemplate('template-1', {
      expectedVersion: 4,
      idempotencyKey: 'deactivate-key-1',
    })
    await activateMessageTemplate('template-1', {
      expectedVersion: 5,
      idempotencyKey: 'activate-key-1',
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/message-templates')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST' })
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({
      template_type: 'interview_invitation',
      name: '默认面试通知',
      subject: '面试通知',
      body: '你好 {{candidate_name}}',
      variables: ['candidate_name'],
      idempotency_key: 'create-key-1',
    })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/message-templates/template-1/versions')
    expect(JSON.parse(fetchMock.mock.calls[1][1]?.body as string)).toEqual({
      expected_version: 3,
      subject: '新版面试通知',
      body: '新版正文',
      variables: ['candidate_name', 'interview_time'],
      idempotency_key: 'version-key-1',
    })
    expect(fetchMock.mock.calls[2][0]).toBe('/api/message-templates/template-1/deactivate')
    expect(JSON.parse(fetchMock.mock.calls[2][1]?.body as string)).toEqual({
      expected_version: 4,
      idempotency_key: 'deactivate-key-1',
    })
    expect(fetchMock.mock.calls[3][0]).toBe('/api/message-templates/template-1/activate')
    expect(JSON.parse(fetchMock.mock.calls[3][1]?.body as string)).toEqual({
      expected_version: 5,
      idempotency_key: 'activate-key-1',
    })
  })

  it('builds communication record query requests', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ items: [], total: 0, limit: 20, offset: 0 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })),
    )
    vi.stubGlobal('fetch', fetchMock)

    await fetchCommunicationRecords({
      contextType: 'offer',
      contextId: 'offer-1',
      applicationId: 'application-1',
      limit: 20,
      offset: 40,
    })
    await fetchCommunicationRecord('record-1')

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/communications?context_type=offer&context_id=offer-1&application_id=application-1&limit=20&offset=40',
    )
    expect(fetchMock.mock.calls[1][0]).toBe('/api/communications/record-1')
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

  it('读取解析详情并通过 POST 重新处理原文件', async () => {
    const detail = { id: 'document-1', text_segments: [] }
    const queued = { id: 'document-1', status: 'queued' }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(detail), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(queued), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      fetchResumeDocumentDetail('job-1', 'batch-1', 'document-1'),
    ).resolves.toEqual(detail)
    await expect(retryResumeParsing('job-1', 'batch-1', 'document-1')).resolves.toEqual(
      queued,
    )

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/jobs/job-1/batches/batch-1/documents/document-1',
    )
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: 'include' })
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/jobs/job-1/batches/batch-1/documents/document-1/parse-retry',
    )
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: 'POST',
      credentials: 'include',
    })
  })

  it('通过 POST 请求 AI 结构化 JD 草稿', async () => {
    const draft = {
      suggested_title: '高级后端工程师',
      summary: '负责核心服务设计与开发。',
      pass_threshold: 60,
      hard_requirements: [],
      scoring_dimensions: [
        {
          name: '系统设计',
          description: '关注可扩展架构',
          weight_percent: 100,
          sort_order: 0,
        },
      ],
    }
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(draft), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(generateJDAIDraft('job-1')).resolves.toEqual(draft)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/jobs/job-1/criteria/ai-draft')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      credentials: 'include',
    })
  })

  it('按后端契约生成门户链接并修正候选人手机号', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: 'link-1', portal_token: 'portal-token' }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            candidate_id: 'candidate-1',
            phone: '13999995678',
            revoked_portal_link_count: 1,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
    vi.stubGlobal('fetch', fetchMock)

    await createOfferPortalLink('offer-1', '11111111-1111-4111-8111-111111111111')
    await updateCandidatePhone('candidate-1', '13999995678', '候选人确认换号')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/offers/offer-1/portal-links')
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({
      idempotency_key: '11111111-1111-4111-8111-111111111111',
    })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/candidates/candidate-1/phone')
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'PATCH' })
    expect(JSON.parse(fetchMock.mock.calls[1][1]?.body as string)).toEqual({
      phone: '13999995678',
      reason: '候选人确认换号',
    })
  })

  it('公共门户验证和回应不会触发内部会话失效事件', async () => {
    const unauthorizedListener = vi.fn()
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, unauthorizedListener)
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: 'verification_required' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: '验证信息不正确' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            candidate_name: '张三',
            job_title: '后端工程师',
            progress: 'accepted',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchOfferPortalStatus('x'.repeat(48))).resolves.toEqual({
      status: 'verification_required',
    })
    await expect(verifyOfferPortal('x'.repeat(48), '1234')).rejects.toEqual(
      new ApiError(401, '验证信息不正确'),
    )
    await respondToOfferPortal(
      'x'.repeat(48),
      'v'.repeat(48),
      'accepted',
      null,
      null,
      '22222222-2222-4222-8222-222222222222',
    )

    expect(unauthorizedListener).not.toHaveBeenCalled()
    expect(JSON.parse(fetchMock.mock.calls[2][1]?.body as string)).toMatchObject({
      decision: 'accepted',
      rejection_reason_code: null,
      rejection_note: null,
      idempotency_key: '22222222-2222-4222-8222-222222222222',
    })
    window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, unauthorizedListener)
  })
})
