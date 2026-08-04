import {
  ArrowLeftOutlined,
  AppstoreOutlined,
  AuditOutlined,
  BarChartOutlined,
  BellOutlined,
  BranchesOutlined,
  CalendarOutlined,
  CloudServerOutlined,
  ContactsOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  FileDoneOutlined,
  LogoutOutlined,
  MailOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  ProfileOutlined,
  ReadOutlined,
  SettingOutlined,
  SolutionOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Badge, Button, Layout, Select, Space, Spin, Tag, Tooltip, Typography } from 'antd'
import { useState, type ReactNode } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { fetchInternalNotificationUnreadCount, fetchJob, fetchJobs, fetchLiveHealth } from '../api/client'
import { useAuth } from '../auth/context'
import {
  businessModuleForPath,
  defaultPathForModule,
  jobIdFromPath,
  safeWorkbenchReturnPath,
  type BusinessModule,
} from './navigation'

const { Header, Sider, Content } = Layout
const { Text } = Typography

interface NavigationItem {
  key: BusinessModule
  label: string
  icon: ReactNode
  path?: string
  badge?: string
}

function pageMeta(pathname: string) {
  if (pathname.startsWith('/workbench')) {
    return { title: '招聘工作台', subtitle: '聚合当前需要处理、等待回应与风险事项' }
  }
  if (pathname.startsWith('/ai-console')) {
    return { title: 'AI 控制台', subtitle: '管理可观测、可追溯、可评测的 AI Agent 工程能力' }
  }
  if (pathname.startsWith('/ai-evaluations')) {
    return { title: 'AI 评测', subtitle: '运行固定样本评测并沉淀错误案例库' }
  }
  if (pathname.startsWith('/prompt-templates')) {
    return { title: 'PromptOps', subtitle: '维护场景化 Prompt 模板、发布版本和回滚历史' }
  }
  if (pathname.startsWith('/recruitment-knowledge')) {
    return { title: '企业知识库', subtitle: '维护招聘知识文档并预览 RAG 检索引用' }
  }
  if (pathname.startsWith('/recruitment-requests')) {
    return { title: '招聘需求', subtitle: '发起、审批并追踪招聘任务来源' }
  }
  if (pathname.startsWith('/candidates')) {
    return { title: '候选人中心', subtitle: '统一查看主档案、应聘历史与重复确认' }
  }
  if (pathname.startsWith('/talent')) {
    return { title: '人才库', subtitle: '沉淀候选人资产并按分组持续运营' }
  }
  if (pathname.startsWith('/offers')) {
    return { title: '录用管理', subtitle: '处理薪酬方案、Offer 审批与入职跟踪' }
  }
  if (pathname.startsWith('/onboardings')) {
    return { title: '入职跟踪', subtitle: '确认入职日期并跟进入职结果' }
  }
  if (pathname.startsWith('/analytics')) {
    return { title: '数据分析', subtitle: '追踪招聘转化、效率与决策质量' }
  }
  if (pathname.startsWith('/notifications')) {
    return { title: '消息中心', subtitle: '查看招聘流程提醒并快速回到对应业务页面' }
  }
  if (pathname.startsWith('/message-templates')) {
    return { title: '沟通模板', subtitle: '维护面试、Offer 和入职沟通文案及版本历史' }
  }
  if (pathname.startsWith('/communications')) {
    return { title: '沟通留痕', subtitle: '查询候选人沟通记录、正文快照和更正历史' }
  }
  if (pathname === '/jobs/new') {
    return { title: '新建职位', subtitle: '录入职位信息并建立筛选标准' }
  }
  if (pathname.endsWith('/edit')) {
    return { title: '编辑职位', subtitle: '维护职位信息与原始 JD' }
  }
  if (pathname.endsWith('/criteria')) {
    return { title: '筛选标准', subtitle: '配置硬性要求、评分维度与版本' }
  }
  if (pathname.endsWith('/batches')) {
    return { title: '简历批次', subtitle: '批量上传并跟踪逐文件处理状态' }
  }
  if (pathname.endsWith('/results')) {
    return { title: '筛选结果', subtitle: '查看 AI 依据并记录招聘专员的最终判断' }
  }
  if (pathname.endsWith('/compare')) {
    return { title: '候选人对比', subtitle: '在同一职位标准下横向比较候选人' }
  }
  if (pathname.endsWith('/pipeline')) {
    return { title: '候选人流程看板', subtitle: '管理 AI 初筛后的人工处理进度' }
  }
  if (pathname.endsWith('/interview-plan')) {
    return { title: '面试方案', subtitle: '配置职位面试轮次、问题和结构化评分表' }
  }
  if (pathname.endsWith('/interview-reports')) {
    return { title: '面试报告', subtitle: '汇总筛选与面试证据并形成最终报告' }
  }
  if (pathname.endsWith('/interview-report')) {
    return { title: '面试报告详情', subtitle: '审阅证据、修订版本并确认报告' }
  }
  if (pathname.endsWith('/history') && pathname.includes('/documents/')) {
    return { title: '候选人资料与版本', subtitle: '修正结构化资料并追踪每次分析结果' }
  }
  if (pathname.startsWith('/settings/users')) {
    return { title: '用户与权限', subtitle: '管理账号、角色和登录状态' }
  }
  return { title: '职位管理', subtitle: '管理招聘职位与版本化筛选标准' }
}

export function AppLayout() {
  const auth = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [logoutError, setLogoutError] = useState<string | null>(null)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const meta = pageMeta(location.pathname)
  const activeModule = businessModuleForPath(location.pathname)
  const jobId = jobIdFromPath(location.pathname)
  const workbenchReturnTo = safeWorkbenchReturnPath(
    new URLSearchParams(location.search).get('returnTo'),
  )
  const canAccessJobs = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter', 'hiring_manager'].includes(role),
  )
  const canAccessRequests = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter', 'hiring_manager', 'approver'].includes(role),
  )
  const canAccessAnalytics = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter', 'hiring_manager', 'approver'].includes(role),
  )
  const canCreateJobs = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter'].includes(role),
  )
  const canAccessCandidateCenter = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter'].includes(role),
  )
  const canAccessTalentPool = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter', 'hiring_manager'].includes(role),
  )
  const canAccessMessageTemplates = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter'].includes(role),
  )
  const canAccessCommunications = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter', 'hiring_manager'].includes(role),
  )
  const canAccessRecruitmentKnowledge = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter', 'hiring_manager'].includes(role),
  )
  const isAdministrator = auth.user?.roles.includes('administrator') ?? false
  const showJobContext = ['jobs', 'screening', 'candidate-process', 'interviews'].includes(
    activeModule,
  )
  const navigationItems: NavigationItem[] = [
    {
      key: 'workbench',
      label: '工作台',
      icon: <AppstoreOutlined />,
      path: '/workbench',
    },
    {
      key: 'ai-console',
      label: 'AI 控制台',
      icon: <CloudServerOutlined />,
      path: '/ai-console',
    },
    ...(isAdministrator
      ? [
          {
            key: 'ai-evaluations' as const,
            label: 'AI评测',
            icon: <ExperimentOutlined />,
            path: '/ai-evaluations',
          },
        ]
      : []),
    ...(isAdministrator
      ? [
          {
            key: 'prompt-templates' as const,
            label: 'PromptOps',
            icon: <BranchesOutlined />,
            path: '/prompt-templates',
          },
        ]
      : []),
    ...(canAccessRecruitmentKnowledge
      ? [
          {
            key: 'recruitment-knowledge' as const,
            label: '企业知识库',
            icon: <ReadOutlined />,
            path: '/recruitment-knowledge',
          },
        ]
      : []),
    ...(canAccessRequests
      ? [
          {
            key: 'requests' as const,
            label: '招聘需求',
            icon: <AuditOutlined />,
            path: '/recruitment-requests',
          },
        ]
      : []),
    ...(canAccessRequests
      ? [
          {
            key: 'hiring' as const,
            label: '录用管理',
            icon: <FileDoneOutlined />,
            path: '/offers',
          },
        ]
      : []),
    ...(canAccessJobs
      ? [
          { key: 'jobs' as const, label: '岗位管理', icon: <ProfileOutlined />, path: '/jobs' },
          {
            key: 'screening' as const,
            label: '智能筛选',
            icon: <FileSearchOutlined />,
            path: jobId ? `/jobs/${jobId}/batches` : undefined,
            badge: jobId ? undefined : '先选岗位',
          },
          {
            key: 'candidate-process' as const,
            label: '候选人流程',
            icon: <TeamOutlined />,
            path: jobId ? `/jobs/${jobId}/pipeline` : undefined,
            badge: jobId ? undefined : '先选岗位',
          },
          ...(canAccessCandidateCenter
            ? [
                {
                  key: 'candidates' as const,
                  label: '候选人中心',
                  icon: <ContactsOutlined />,
                  path: '/candidates',
                },
              ]
            : []),
          {
            key: 'interviews' as const,
            label: '面试管理',
            icon: <CalendarOutlined />,
            path: jobId ? `/jobs/${jobId}/interview-plan` : undefined,
            badge: jobId ? undefined : '先选岗位',
          },
          ...(canAccessTalentPool
            ? [
                {
                  key: 'talent' as const,
                  label: '人才库',
                  icon: <DatabaseOutlined />,
                  path: '/talent',
                },
              ]
            : []),
        ]
      : []),
    ...(canAccessAnalytics
      ? [
          {
            key: 'analytics' as const,
            label: '数据分析',
            icon: <BarChartOutlined />,
            path: '/analytics',
          },
        ]
      : []),
    ...(canAccessMessageTemplates
      ? [
          {
            key: 'message-templates' as const,
            label: '沟通模板',
            icon: <BellOutlined />,
            path: '/message-templates',
          },
        ]
      : []),
    ...(canAccessCommunications
      ? [
          {
            key: 'communications' as const,
            label: '沟通留痕',
            icon: <MailOutlined />,
            path: '/communications',
          },
        ]
      : []),
  ]
  const health = useQuery({
    queryKey: ['health', 'live'],
    queryFn: fetchLiveHealth,
    staleTime: 30_000,
  })
  const notificationUnreadCount = useQuery({
    queryKey: ['notifications', 'unread-count'],
    queryFn: fetchInternalNotificationUnreadCount,
    enabled: Boolean(auth.user),
    staleTime: 15_000,
    refetchInterval: 60_000,
  })
  const jobs = useQuery({
    queryKey: ['jobs', { includeArchived: true }],
    queryFn: () => fetchJobs(true),
    enabled: Boolean(canAccessJobs),
    staleTime: 30_000,
  })
  const currentJob = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
    staleTime: 30_000,
  })
  const selectedJob = currentJob.data ?? jobs.data?.find((job) => job.id === jobId)

  async function handleLogout() {
    setLogoutError(null)
    try {
      await auth.logout()
      navigate('/login', { replace: true })
    } catch {
      setLogoutError('退出失败，请稍后重试')
    }
  }

  function handleJobChange(nextJobId: string) {
    navigate(defaultPathForModule(activeModule, nextJobId))
    setMobileNavOpen(false)
  }

  return (
    <Layout className="app-shell">
      <Sider
        width={264}
        className={`app-sider${mobileNavOpen ? ' is-open' : ''}`}
        trigger={null}
      >
        <button
          className="brand-button sidebar-brand"
          type="button"
          onClick={() => navigate('/workbench')}
        >
          <span className="brand-mark" aria-hidden="true">
            <SolutionOutlined />
          </span>
          <span>
            <Text className="brand-name">SmartHR</Text>
            <Text className="brand-subtitle">智能招聘平台</Text>
          </span>
        </button>

        <nav className="sidebar-nav" aria-label="主导航">
          <Text className="nav-caption">业务模块</Text>
          {navigationItems.map((item) => {
            const active = activeModule === item.key
            return (
              <button
                key={item.key}
                type="button"
                className={`nav-item${active ? ' is-active' : ''}`}
                aria-label={item.label}
                aria-current={active ? 'page' : undefined}
                disabled={!item.path}
                title={!item.path && item.badge === '先选岗位' ? '请先选择一个岗位' : undefined}
                onClick={() => {
                  if (!item.path) return
                  navigate(item.path)
                  setMobileNavOpen(false)
                }}
              >
                {item.icon}
                <span>{item.label}</span>
                {item.badge && <small>{item.badge}</small>}
              </button>
            )
          })}
        </nav>

        <div className="sidebar-footer">
          <button
            type="button"
            className={`nav-item${activeModule === 'settings' ? ' is-active' : ''}`}
            aria-label="系统设置"
            aria-current={activeModule === 'settings' ? 'page' : undefined}
            disabled={!isAdministrator}
            onClick={() => {
              if (!isAdministrator) return
              navigate('/settings/users')
              setMobileNavOpen(false)
            }}
          >
            <SettingOutlined />
            <span>系统设置</span>
          </button>
          <div className="sidebar-service-card" aria-label="服务状态">
            <span className="service-dot" />
            <span>系统服务</span>
            {health.isPending && <Spin size="small" />}
            {health.isError && <Tag color="error">异常</Tag>}
            {health.isSuccess && <Tag color="success">正常</Tag>}
          </div>
        </div>
      </Sider>

      <Layout className="workspace-shell">
        <Header className="app-header">
          <div className="header-title-group">
            <Button
              className="mobile-menu-button"
              aria-label={mobileNavOpen ? '收起导航' : '展开导航'}
              icon={mobileNavOpen ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />}
              onClick={() => setMobileNavOpen((open) => !open)}
            />
            {workbenchReturnTo && (
              <Button
                className="workbench-return-button"
                aria-label="返回工作台"
                icon={<ArrowLeftOutlined />}
                onClick={() => navigate(workbenchReturnTo)}
              >
                返回工作台
              </Button>
            )}
            <div>
              <div className="header-page-title">{meta.title}</div>
              <Text className="header-page-subtitle">{meta.subtitle}</Text>
            </div>
          </div>

          {showJobContext && (
            <div className="current-job-context" aria-label="当前岗位上下文">
              <Text className="current-job-label">当前岗位</Text>
              <Select
                className="current-job-select"
                aria-label="切换当前岗位"
                showSearch
                value={jobId ?? undefined}
                placeholder={jobs.isPending ? '正在读取岗位…' : '选择一个岗位'}
                loading={jobs.isPending}
                status={jobs.isError ? 'error' : undefined}
                optionFilterProp="label"
                options={(jobs.data ?? []).map((job) => ({
                  value: job.id,
                  label: `${job.title}${job.status === 'archived' ? '（已归档）' : ''}`,
                }))}
                onChange={handleJobChange}
              />
              <div className="current-job-meta" aria-live="polite">
                {selectedJob ? (
                  <>
                    <Text ellipsis>{selectedJob.department || '未填写部门'}</Text>
                    <Tag color={selectedJob.status === 'active' ? 'success' : 'default'}>
                      {selectedJob.status === 'active' ? '招聘中' : '已归档'}
                    </Tag>
                  </>
                ) : (
                  <Text type={jobs.isError ? 'danger' : 'secondary'}>
                    {jobs.isError ? '岗位列表读取失败' : '选择后进入岗位业务'}
                  </Text>
                )}
              </div>
            </div>
          )}

          <Space size="middle" className="header-actions">
            {canCreateJobs && activeModule === 'jobs' && (
              <Button
                type="primary"
                icon={<PlusOutlined />}
                className="header-primary-action"
                onClick={() => navigate('/jobs/new')}
              >
                发布职位
              </Button>
            )}
            <Tooltip title="消息中心">
              <Badge count={notificationUnreadCount.data?.unread_count ?? 0} size="small">
                <Button
                  aria-label="消息中心"
                  icon={<BellOutlined />}
                  onClick={() => navigate('/notifications')}
                />
              </Badge>
            </Tooltip>
            <div className="account-label">
              <span className="account-avatar" aria-hidden="true">
                <UserOutlined />
              </span>
              <Text>{auth.user?.display_name}</Text>
            </div>
            <Tooltip title="退出登录">
              <Button
                aria-label="退出登录"
                icon={<LogoutOutlined />}
                loading={auth.isLoggingOut}
                onClick={() => void handleLogout()}
              />
            </Tooltip>
          </Space>
        </Header>

        <Content className="app-content">
          {logoutError && (
            <Alert type="error" showIcon message={logoutError} closable className="page-alert" />
          )}
          <Outlet />
        </Content>
      </Layout>
      {mobileNavOpen && (
        <button
          type="button"
          aria-label="关闭导航遮罩"
          className="sidebar-backdrop"
          onClick={() => setMobileNavOpen(false)}
        />
      )}
    </Layout>
  )
}
