import { Result } from 'antd'
import { Outlet } from 'react-router-dom'

import type { RoleKey } from '../api/client'
import { useAuth } from './context'

export function RoleRoute({ roles }: { roles: RoleKey[] }) {
  const auth = useAuth()
  const allowed = auth.user?.roles.some((role) => roles.includes(role)) ?? false

  if (!allowed) {
    return <Result status="403" title="无权访问" subTitle="当前账号没有该功能的访问权限。" />
  }

  return <Outlet />
}
