import { ApiOutlined, FileSearchOutlined, LogoutOutlined, UserOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Empty, Layout, Space, Spin, Tag, Tooltip, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fetchLiveHealth } from '../api/client'
import { useAuth } from '../auth/context'

const { Header, Content } = Layout
const { Title, Text } = Typography

export function DashboardPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [logoutError, setLogoutError] = useState<string | null>(null)
  const health = useQuery({
    queryKey: ['health', 'live'],
    queryFn: fetchLiveHealth,
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
      <Header className="app-header">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            S
          </div>
          <div>
            <Text className="brand-name">SmartHR</Text>
            <Text className="brand-subtitle">AI 简历筛选工作台</Text>
          </div>
        </div>

        <Space size="middle">
          <div className="account-label">
            <UserOutlined />
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

        <div className="page-heading">
          <div>
            <Title level={2}>职位筛选</Title>
            <Text type="secondary">管理职位与候选人筛选批次</Text>
          </div>
          <div className="service-status" aria-label="服务状态">
            <ApiOutlined />
            {health.isPending && <Spin size="small" />}
            {health.isError && <Tag color="error">服务异常</Tag>}
            {health.isSuccess && <Tag color="success">服务正常</Tag>}
          </div>
        </div>

        <section className="empty-workspace" aria-label="职位列表">
          <Empty
            image={<FileSearchOutlined className="empty-icon" />}
            description="暂无职位"
          />
        </section>
      </Content>
    </Layout>
  )
}
