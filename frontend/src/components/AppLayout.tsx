import {
  AppstoreOutlined,
  BarChartOutlined,
  BellOutlined,
  CalendarOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  ProfileOutlined,
  SettingOutlined,
  SolutionOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Layout, Select, Space, Spin, Tag, Tooltip, Typography } from 'antd'
import { useState, type ReactNode } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { fetchJob, fetchJobs, fetchLiveHealth } from '../api/client'
import { useAuth } from '../auth/context'
import {
  businessModuleForPath,
  defaultPathForModule,
  jobIdFromPath,
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
  if (pathname.endsWith('/history') && pathname.includes('/documents/')) {
    return { title: '候选人资料与版本', subtitle: '修正结构化资料并追踪每次分析结果' }
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
  const navigationItems: NavigationItem[] = [
    {
      key: 'workbench',
      label: '工作台',
      icon: <AppstoreOutlined />,
      badge: '待开发',
    },
    { key: 'jobs', label: '岗位管理', icon: <ProfileOutlined />, path: '/' },
    {
      key: 'screening',
      label: '智能筛选',
      icon: <FileSearchOutlined />,
      path: jobId ? `/jobs/${jobId}/batches` : undefined,
      badge: jobId ? undefined : '先选岗位',
    },
    {
      key: 'candidate-process',
      label: '候选人流程',
      icon: <TeamOutlined />,
      path: jobId ? `/jobs/${jobId}/pipeline` : undefined,
      badge: jobId ? undefined : '先选岗位',
    },
    {
      key: 'interviews',
      label: '面试管理',
      icon: <CalendarOutlined />,
      path: jobId ? `/jobs/${jobId}/interview-plan` : undefined,
      badge: jobId ? undefined : '先选岗位',
    },
    { key: 'talent', label: '人才库', icon: <DatabaseOutlined />, badge: '待开发' },
    { key: 'analytics', label: '数据分析', icon: <BarChartOutlined />, badge: '待开发' },
  ]
  const health = useQuery({
    queryKey: ['health', 'live'],
    queryFn: fetchLiveHealth,
    staleTime: 30_000,
  })
  const jobs = useQuery({
    queryKey: ['jobs', { includeArchived: true }],
    queryFn: () => fetchJobs(true),
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
        <button className="brand-button sidebar-brand" type="button" onClick={() => navigate('/')}>
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
          <button type="button" className="nav-item" aria-label="系统设置" disabled>
            <SettingOutlined />
            <span>系统设置</span>
            <small>待开发</small>
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
            <div>
              <div className="header-page-title">{meta.title}</div>
              <Text className="header-page-subtitle">{meta.subtitle}</Text>
            </div>
          </div>

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

          <Space size="middle" className="header-actions">
            <Button
              type="primary"
              icon={<PlusOutlined />}
              className="header-primary-action"
              onClick={() => navigate('/jobs/new')}
            >
              发布职位
            </Button>
            <Tooltip title="消息中心将在后续功能开放">
              <Button aria-label="消息中心" icon={<BellOutlined />} disabled />
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
