import { Tabs } from 'antd'
import { useNavigate } from 'react-router-dom'

type InterviewSection = 'plan' | 'reports'

interface InterviewModuleNavProps {
  jobId?: string
  activeKey: InterviewSection
}

const sectionPaths: Record<InterviewSection, string> = {
  plan: 'interview-plan',
  reports: 'interview-reports',
}

const items = [
  { key: 'plan', label: '面试方案' },
  { key: 'reports', label: '面试报告' },
]

export function InterviewModuleNav({ jobId, activeKey }: InterviewModuleNavProps) {
  const navigate = useNavigate()

  if (!jobId) return null

  return (
    <nav className="screening-module-nav interview-module-nav" aria-label="面试管理页面">
      <Tabs
        activeKey={activeKey}
        items={items}
        onChange={(key) =>
          navigate(`/jobs/${jobId}/${sectionPaths[key as InterviewSection]}`)
        }
      />
    </nav>
  )
}
