import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { ScreeningModuleNav } from './ScreeningModuleNav'

function LocationProbe() {
  return <span data-testid="location">{useLocation().pathname}</span>
}

describe('ScreeningModuleNav', () => {
  it('展示固定二级导航并切换到同一职位的目标页面', () => {
    render(
      <MemoryRouter initialEntries={['/jobs/job-1/batches']}>
        <ScreeningModuleNav jobId="job-1" activeKey="batches" />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByRole('tab', { name: '简历批次' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    fireEvent.click(screen.getByRole('tab', { name: '筛选结果' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/jobs/job-1/results')
  })
})
