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
const CandidateComparisonPage = lazy(() =>
  import('./pages/CandidateComparisonPage').then((module) => ({
    default: module.CandidateComparisonPage,
  })),
)
const CandidateHistoryPage = lazy(() =>
  import('./pages/CandidateHistoryPage').then((module) => ({
    default: module.CandidateHistoryPage,
  })),
)
const CandidateProcessPage = lazy(() =>
  import('./pages/CandidateProcessPage').then((module) => ({
    default: module.CandidateProcessPage,
  })),
)
const InterviewPlanPage = lazy(() =>
  import('./pages/InterviewPlanPage').then((module) => ({
    default: module.InterviewPlanPage,
  })),
)
const InterviewSchedulePage = lazy(() =>
  import('./pages/InterviewSchedulePage').then((module) => ({
    default: module.InterviewSchedulePage,
  })),
)
const InterviewEvaluationPage = lazy(() =>
  import('./pages/InterviewEvaluationPage').then((module) => ({
    default: module.InterviewEvaluationPage,
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
                <Route path="/jobs/:jobId" element={<JobListPage />} />
                <Route path="/jobs/new" element={<JobFormPage />} />
                <Route path="/jobs/:jobId/edit" element={<JobFormPage />} />
                <Route path="/jobs/:jobId/criteria" element={<CriteriaPage />} />
                <Route path="/jobs/:jobId/batches" element={<BatchPage />} />
                <Route path="/jobs/:jobId/results" element={<ScreeningResultsPage />} />
                <Route path="/jobs/:jobId/compare" element={<CandidateComparisonPage />} />
                <Route path="/jobs/:jobId/pipeline" element={<CandidateProcessPage />} />
                <Route path="/jobs/:jobId/interview-plan" element={<InterviewPlanPage />} />
                <Route
                  path="/jobs/:jobId/candidates/:documentId/interview-schedule"
                  element={<InterviewSchedulePage />}
                />
                <Route
                  path="/jobs/:jobId/candidates/:documentId/interview-evaluations/:roundId"
                  element={<InterviewEvaluationPage />}
                />
                <Route
                  path="/jobs/:jobId/batches/:batchId/documents/:documentId/history"
                  element={<CandidateHistoryPage />}
                />
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
