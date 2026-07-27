import { Tabs } from 'antd'
import { useNavigate } from 'react-router-dom'

type ScreeningSection = 'criteria' | 'batches' | 'results'

interface ScreeningModuleNavProps {
  jobId?: string
  activeKey: ScreeningSection
}

const sectionPaths: Record<ScreeningSection, string> = {
  criteria: 'criteria',
  batches: 'batches',
  results: 'results',
}

const items = [
  { key: 'criteria', label: '筛选标准' },
  { key: 'batches', label: '简历批次' },
  { key: 'results', label: '筛选结果' },
]

export function ScreeningModuleNav({ jobId, activeKey }: ScreeningModuleNavProps) {
  const navigate = useNavigate()

  if (!jobId) return null

  return (
    <nav className="screening-module-nav" aria-label="智能筛选页面">
      <Tabs
        activeKey={activeKey}
        items={items}
        onChange={(key) =>
          navigate(`/jobs/${jobId}/${sectionPaths[key as ScreeningSection]}`)
        }
      />
    </nav>
  )
}
