import { ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Spin } from 'antd'
import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from './context'

export function ProtectedRoute() {
  const auth = useAuth()
  const location = useLocation()

  if (auth.isLoading) {
    return (
      <div className="full-page-state" aria-label="正在检查登录状态">
        <Spin size="large" />
      </div>
    )
  }

  if (auth.error) {
    return (
      <div className="full-page-state">
        <Alert
          type="error"
          showIcon
          message="无法连接认证服务"
          action={
            <Button icon={<ReloadOutlined />} onClick={() => void auth.retry()}>
              重试
            </Button>
          }
        />
      </div>
    )
  }

  if (!auth.user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
