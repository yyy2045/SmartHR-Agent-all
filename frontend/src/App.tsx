import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { lazy, Suspense } from 'react'

import { AuthProvider } from './auth/AuthProvider'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './components/AppLayout'
import { LoginPage } from './pages/LoginPage'

const CriteriaPage = lazy(() =>
  import('./pages/CriteriaPage').then((module) => ({ default: module.CriteriaPage })),
)
const BatchPage = lazy(() =>
  import('./pages/BatchPage').then((module) => ({ default: module.BatchPage })),
)
const JobFormPage = lazy(() =>
  import('./pages/JobFormPage').then((module) => ({ default: module.JobFormPage })),
)
const JobListPage = lazy(() =>
  import('./pages/JobListPage').then((module) => ({ default: module.JobListPage })),
)
const ScreeningResultsPage = lazy(() =>
  import('./pages/ScreeningResultsPage').then((module) => ({
    default: module.ScreeningResultsPage,
  })),
)

function PageFallback() {
  return <div className="page-fallback">正在加载页面…</div>
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<ProtectedRoute />}>
              <Route element={<AppLayout />}>
                <Route path="/" element={<JobListPage />} />
                <Route path="/jobs/new" element={<JobFormPage />} />
                <Route path="/jobs/:jobId/edit" element={<JobFormPage />} />
                <Route path="/jobs/:jobId/criteria" element={<CriteriaPage />} />
                <Route path="/jobs/:jobId/batches" element={<BatchPage />} />
                <Route path="/jobs/:jobId/results" element={<ScreeningResultsPage />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
