import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { AIConsolePage } from './pages/AIConsolePage'

describe('AI 控制台页面', () => {
  it('展示 AI 工程化专项入口和后续能力卡片', () => {
    render(<AIConsolePage />)

    expect(screen.getByRole('heading', { name: 'AI Agent 工程化专项' })).toBeInTheDocument()
    expect(screen.getByText('AI 调用日志与任务中心')).toBeInTheDocument()
    expect(screen.getByText('Prompt 模板管理与版本化')).toBeInTheDocument()
    expect(screen.getByText('企业招聘知识库 RAG')).toBeInTheDocument()
    expect(screen.getByText('候选人问答 Agent')).toBeInTheDocument()
    expect(screen.getByText('AI 评测与错误案例库')).toBeInTheDocument()
    expect(screen.getByText('AI-01')).toBeInTheDocument()
  })
})
