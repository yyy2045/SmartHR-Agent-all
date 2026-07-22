import {
  ApiOutlined,
  BarChartOutlined,
  BellOutlined,
  FileSearchOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  SearchOutlined,
  SettingOutlined,
  SolutionOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Input, Layout, Space, Spin, Tag, Tooltip, Typography } from 'antd'
import { useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { fetchLiveHealth } from '../api/client'
import { useAuth } from '../auth/context'

const { Header, Sider, Content } = Layout
const { Text } = Typography

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
  return { title: '职位管理', subtitle: '管理招聘职位与版本化筛选标准' }
}

export function AppLayout() {
  const auth = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [logoutError, setLogoutError] = useState<string | null>(null)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const meta = pageMeta(location.pathname)
  const health = useQuery({
    queryKey: ['health', 'live'],
    queryFn: fetchLiveHealth,
    staleTime: 30_000,
  })

  async function handleLogout() {
    setLogoutError(null)
    try {
      await auth.logout()
      navigate('/login', { replace: true })
    } catch {
      setLogoutError('退出失败，请稍后重试')
    }
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
          <Text className="nav-caption">导航</Text>
          <button
            type="button"
            className="nav-item is-active"
            onClick={() => {
              navigate('/')
              setMobileNavOpen(false)
            }}
          >
            <FileSearchOutlined />
            <span>职位管理</span>
          </button>
          <button type="button" className="nav-item" disabled>
            <ApiOutlined />
            <span>AI 智能匹配</span>
            <small>待开发</small>
          </button>
          <button type="button" className="nav-item" disabled>
            <TeamOutlined />
            <span>候选人库</span>
          </button>
          <button type="button" className="nav-item" disabled>
            <BarChartOutlined />
            <span>数据分析</span>
          </button>
        </nav>

        <div className="sidebar-footer">
          <button type="button" className="nav-item" disabled>
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
            <div>
              <div className="header-page-title">{meta.title}</div>
              <Text className="header-page-subtitle">{meta.subtitle}</Text>
            </div>
          </div>

          <Space size="middle" className="header-actions">
            <Input
              className="header-search"
              prefix={<SearchOutlined />}
              placeholder="搜索职位、候选人…"
              aria-label="搜索职位、候选人"
              disabled
            />
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
