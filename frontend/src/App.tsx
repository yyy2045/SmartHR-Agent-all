import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { lazy, Suspense } from 'react'

import { AuthProvider } from './auth/AuthProvider'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { RoleRoute } from './auth/RoleRoute'
import { AppLayout } from './components/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { ChangePasswordPage } from './pages/ChangePasswordPage'
import { useAuth } from './auth/context'

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
const InterviewReportListPage = lazy(() =>
  import('./pages/InterviewReportListPage').then((module) => ({
    default: module.InterviewReportListPage,
  })),
)
const InterviewReportPage = lazy(() =>
  import('./pages/InterviewReportPage').then((module) => ({
    default: module.InterviewReportPage,
  })),
)
const UserManagementPage = lazy(() =>
  import('./pages/UserManagementPage').then((module) => ({
    default: module.UserManagementPage,
  })),
)
const RecruitmentRequestPage = lazy(() =>
  import('./pages/RecruitmentRequestPage').then((module) => ({
    default: module.RecruitmentRequestPage,
  })),
)
const CandidateCenterPage = lazy(() =>
  import('./pages/CandidateCenterPage').then((module) => ({
    default: module.CandidateCenterPage,
  })),
)
const OfferManagementPage = lazy(() =>
  import('./pages/OfferManagementPage').then((module) => ({
    default: module.OfferManagementPage,
  })),
)

function PageFallback() {
  return <div className="page-fallback">正在加载页面…</div>
}

function HomeRoute() {
  const auth = useAuth()
  const canAccessJobs = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter', 'hiring_manager'].includes(role),
  )
  return canAccessJobs ? <JobListPage /> : <Navigate to="/recruitment-requests" replace />
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<ProtectedRoute />}>
              <Route path="/change-password" element={<ChangePasswordPage />} />
              <Route element={<AppLayout />}>
                <Route path="/" element={<HomeRoute />} />
                <Route
                  element={
                    <RoleRoute
                      roles={['administrator', 'recruiter', 'hiring_manager', 'approver']}
                    />
                  }
                >
                  <Route path="/recruitment-requests" element={<RecruitmentRequestPage />} />
                  <Route path="/offers" element={<OfferManagementPage />} />
                </Route>
                <Route
                  element={
                    <RoleRoute roles={['administrator', 'recruiter', 'hiring_manager']} />
                  }
                >
                  <Route path="/jobs/:jobId" element={<JobListPage />} />
                  <Route path="/jobs/:jobId/edit" element={<JobFormPage />} />
                  <Route path="/jobs/:jobId/criteria" element={<CriteriaPage />} />
                  <Route path="/jobs/:jobId/batches" element={<BatchPage />} />
                  <Route path="/jobs/:jobId/results" element={<ScreeningResultsPage />} />
                  <Route path="/jobs/:jobId/compare" element={<CandidateComparisonPage />} />
                  <Route path="/jobs/:jobId/pipeline" element={<CandidateProcessPage />} />
                  <Route path="/jobs/:jobId/interview-plan" element={<InterviewPlanPage />} />
                  <Route
                    path="/jobs/:jobId/interview-reports"
                    element={<InterviewReportListPage />}
                  />
                  <Route
                    path="/jobs/:jobId/applications/:applicationId/interview-report"
                    element={<InterviewReportPage />}
                  />
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
                <Route element={<RoleRoute roles={['administrator', 'recruiter']} />}>
                  <Route path="/jobs/new" element={<JobFormPage />} />
                  <Route path="/candidates" element={<CandidateCenterPage />} />
                </Route>
                <Route element={<RoleRoute roles={['administrator']} />}>
                  <Route path="/settings/users" element={<UserManagementPage />} />
                </Route>
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
