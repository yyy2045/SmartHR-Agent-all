import { Tabs } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/context'

export function HiringModuleNav() {
  const auth = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const canAccessOnboarding = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter', 'hiring_manager'].includes(role),
  )

  return (
    <Tabs
      className="hiring-module-nav"
      activeKey={location.pathname.startsWith('/onboardings') ? 'onboardings' : 'offers'}
      onChange={(key) => navigate(key === 'onboardings' ? '/onboardings' : '/offers')}
      items={[
        { key: 'offers', label: 'Offer 审批' },
        ...(canAccessOnboarding
          ? [{ key: 'onboardings', label: '入职跟踪' }]
          : []),
      ]}
    />
  )
}
