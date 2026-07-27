export interface HealthResponse {
  status: string
}

export interface AuthUser {
  id: string
  username: string
  display_name: string
  is_active: boolean
  must_change_password: boolean
  roles: RoleKey[]
}

export type RoleKey = 'administrator' | 'recruiter' | 'hiring_manager' | 'approver'

export interface LoginCredentials {
  username: string
  password: string
}

export interface ChangePasswordInput {
  current_password: string
  new_password: string
}

export type JobStatus = 'active' | 'archived'
export type CriteriaStatus = 'draft' | 'confirmed'
export type InterviewPlanStatus = 'draft' | 'confirmed'
export type InterviewRoundType = 'phone' | 'technical' | 'business' | 'hr' | 'final' | 'other'
export type HardRequirementType =
  | 'min_experience_years'
  | 'min_education'
  | 'required_certification'
  | 'language_level'
  | 'other'

export interface JobInput {
  title: string
  department: string
  original_jd: string
  recruiter_id?: string
  hiring_manager_id?: string | null
}

export interface JobRecord extends JobInput {
  id: string
  recruiter_id: string
  hiring_manager_id: string | null
  recruitment_request_id: string | null
  status: JobStatus
  archived_at: string | null
  created_at: string
  updated_at: string
}

export type RecruitmentRequestStatus =
  | 'draft'
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'converted'
export type RecruitmentRequestPriority = 'urgent' | 'high' | 'normal' | 'low'
export type RecruitmentRequestDecision = 'approved' | 'rejected'

export interface UserReference {
  id: string
  username: string
  display_name: string
}

export interface RecruitmentRequestContentInput {
  job_title: string
  headcount: number
  reason: string
  priority: RecruitmentRequestPriority
  target_start_date: string
  salary_min: number
  salary_max: number
  notes: string
}

export interface RecruitmentRequestVersion extends RecruitmentRequestContentInput {
  id: string
  version_number: number
  source_version_id: string | null
  created_by_id: string | null
  created_by_username: string
  created_by_display_name: string
  created_at: string
}

export interface RecruitmentRequestApproval {
  id: string
  version_id: string
  approver_id: string | null
  approver_username: string
  approver_display_name: string
  decision: RecruitmentRequestDecision
  comment: string
  decided_at: string
}

export interface RecruitmentRequestRecord {
  id: string
  idempotency_key: string
  requester: UserReference
  recruiter: UserReference
  created_by: UserReference
  status: RecruitmentRequestStatus
  current_version_number: number
  current_version: RecruitmentRequestVersion
  linked_job_id: string | null
  versions: RecruitmentRequestVersion[]
  approvals: RecruitmentRequestApproval[]
  created_at: string
  updated_at: string
}

export interface RecruitmentRequestCreateInput extends RecruitmentRequestContentInput {
  idempotency_key: string
  requester_id?: string
  recruiter_id: string
}

export interface RecruitmentRequestVersionCreateInput
  extends RecruitmentRequestContentInput {
  source_version_id: string
}

export interface RecruitmentRequestJobInput {
  department: string
  original_jd: string
}

export interface HardRequirementInput {
  requirement_type: HardRequirementType
  title: string
  description: string
  expected_value: string
  auto_reject: boolean
  sort_order: number
}

export interface HardRequirement extends HardRequirementInput {
  id: string
}

export interface ScoringDimensionInput {
  name: string
  description: string
  weight_percent: number
  sort_order: number
}

export interface ScoringDimension extends ScoringDimensionInput {
  id: string
}

export interface CriteriaVersion {
  id: string
  job_id: string
  version_number: number
  status: CriteriaStatus
  pass_threshold: number
  source_version_id: string | null
  confirmed_by_id: string | null
  confirmed_at: string | null
  created_at: string
  updated_at: string
  hard_requirements: HardRequirement[]
  scoring_dimensions: ScoringDimension[]
}

export interface CriteriaDraftInput {
  pass_threshold: number
  hard_requirements: HardRequirementInput[]
  scoring_dimensions: ScoringDimensionInput[]
}

export interface JDAIDraft extends CriteriaDraftInput {
  suggested_title: string
  summary: string
}

export interface JobDetail extends JobRecord {
  criteria_versions: CriteriaVersion[]
}

export interface InterviewScoreAnchorInput {
  score_value: number
  description: string
}

export interface InterviewScoreAnchor extends InterviewScoreAnchorInput {
  id: string
}

export interface InterviewScoreDimensionInput {
  name: string
  description: string
  weight_percent: number
  sort_order: number
  anchors: InterviewScoreAnchorInput[]
}

export interface InterviewScoreDimension extends InterviewScoreDimensionInput {
  id: string
  anchors: InterviewScoreAnchor[]
}

export interface InterviewQuestionInput {
  question_text: string
  evaluation_guide: string
  sort_order: number
}

export interface InterviewQuestion extends InterviewQuestionInput {
  id: string
}

export interface InterviewRoundInput {
  name: string
  round_type: InterviewRoundType
  duration_minutes: number
  pass_threshold: number
  focus: string
  sort_order: number
  questions: InterviewQuestionInput[]
  scoring_dimensions: InterviewScoreDimensionInput[]
}

export interface InterviewRound extends InterviewRoundInput {
  id: string
  questions: InterviewQuestion[]
  scoring_dimensions: InterviewScoreDimension[]
}

export interface InterviewPlanDraftInput {
  rounds: InterviewRoundInput[]
}

export interface InterviewPlanVersion {
  id: string
  job_id: string
  version_number: number
  status: InterviewPlanStatus
  source_version_id: string | null
  confirmed_by_id: string | null
  confirmed_at: string | null
  created_at: string
  updated_at: string
  rounds: InterviewRound[]
}

export type InterviewMethod = 'onsite' | 'online' | 'phone'
export type InterviewScheduleStatus = 'scheduled' | 'partially_cancelled' | 'cancelled'
export type InterviewScheduleRoundStatus = 'scheduled' | 'rescheduled' | 'cancelled'

export interface InterviewScheduleRoundArrangementInput {
  scheduled_start_at: string
  interview_method: InterviewMethod
  location: string | null
  meeting_url: string | null
}

export interface InterviewScheduleRoundCreateInput
  extends InterviewScheduleRoundArrangementInput {
  plan_round_id: string
}

export interface InterviewScheduleCreateInput {
  plan_version_id: string
  rounds: InterviewScheduleRoundCreateInput[]
}

export interface InterviewRoundRescheduleInput
  extends InterviewScheduleRoundArrangementInput {
  reason: string
}

export interface InterviewScheduleRoundRecord {
  id: string
  plan_round_id: string
  name: string
  round_type: InterviewRoundType
  duration_minutes: number
  sort_order: number
  scheduled_start_at: string
  interview_method: InterviewMethod
  location: string | null
  meeting_url: string | null
  status: InterviewScheduleRoundStatus
  reschedule_count: number
  last_change_reason: string | null
  updated_by_id: string | null
  cancelled_at: string | null
  created_at: string
  updated_at: string
}

export interface InterviewScheduleRecord {
  id: string
  document_id: string
  candidate_code: string
  plan_version_id: string
  plan_version_number: number
  status: InterviewScheduleStatus
  created_by_id: string | null
  created_at: string
  updated_at: string
  rounds: InterviewScheduleRoundRecord[]
}

export type InterviewEvaluationStatus = 'draft' | 'submitted'
export type OverallRecommendation =
  | 'strongly_recommend'
  | 'recommend'
  | 'reserve'
  | 'not_recommend'

export interface InterviewQuestionResponseInput {
  question_id: string
  answer_summary: string
  evidence: string
}

export interface InterviewDimensionRatingInput {
  dimension_id: string
  score: number | null
  evidence: string
}

export interface InterviewEvaluationDraftInput {
  overall_recommendation: OverallRecommendation | null
  overall_comment: string
  question_responses: InterviewQuestionResponseInput[]
  dimension_ratings: InterviewDimensionRatingInput[]
}

export interface InterviewQuestionResponseRecord extends InterviewQuestionResponseInput {
  id: string
}

export interface InterviewDimensionRatingRecord extends InterviewDimensionRatingInput {
  id: string
}

export interface InterviewEvaluationRecord {
  id: string
  status: InterviewEvaluationStatus
  overall_recommendation: OverallRecommendation | null
  overall_comment: string
  total_score: number | null
  passed: boolean | null
  submitted_by_id: string | null
  submitted_at: string | null
  created_at: string
  updated_at: string
  question_responses: InterviewQuestionResponseRecord[]
  dimension_ratings: InterviewDimensionRatingRecord[]
}

export interface InterviewEvaluationQuestionContext {
  id: string
  question_text: string
  evaluation_guide: string
  sort_order: number
}

export interface InterviewEvaluationDimensionContext {
  id: string
  name: string
  description: string
  weight_percent: number
  sort_order: number
  anchors: Array<{ score_value: number; description: string }>
}

export interface InterviewEvaluationContext {
  round_id: string
  plan_round_id: string
  round_name: string
  round_type: InterviewRoundType
  round_status: InterviewScheduleRoundStatus
  pass_threshold: number
  scheduled_start_at: string
  questions: InterviewEvaluationQuestionContext[]
  dimensions: InterviewEvaluationDimensionContext[]
  evaluation: InterviewEvaluationRecord | null
}

export type InterviewReportStatus = 'draft' | 'confirmed'
export type InterviewReportConclusion = 'hire' | 'next_round' | 'reserve' | 'reject'

export interface ReportScreeningCitation {
  id: string
  subject_type: string
  subject_key: string
  quote: string
  source_type: string
  page_number: number | null
  paragraph_index: number | null
}

export interface ReportScreeningEvidence {
  id: string
  document_id: string
  criteria_version_id: string
  analysis_version: number
  ai_group: 'passed' | 'low_match' | 'auto_rejected' | null
  total_score: number | null
  pass_threshold: number
  current_decision: 'unprocessed' | 'shortlisted' | 'pending' | 'rejected'
  strengths: string[]
  gaps: string[]
  missing_items: string[]
  completed_at: string | null
  citations: ReportScreeningCitation[]
}

export interface ReportQuestionEvidence {
  question_id: string
  question_text: string
  answer_summary: string
  evidence: string
}

export interface ReportDimensionEvidence {
  dimension_id: string
  dimension_name: string
  score: number | null
  evidence: string
}

export interface ReportSubmittedEvaluation {
  evaluation_id: string
  round_id: string
  round_name: string
  round_type: string
  sort_order: number
  total_score: number | null
  passed: boolean | null
  overall_recommendation: string
  overall_comment: string
  submitted_at: string
  question_responses: ReportQuestionEvidence[]
  dimension_ratings: ReportDimensionEvidence[]
}

export interface ReportMissingRound {
  round_id: string
  round_name: string
  round_type: string
  sort_order: number
  round_status: InterviewScheduleRoundStatus
  reason: 'not_submitted' | 'cancelled'
}

export interface InterviewReportContext {
  application_id: string
  application_status: 'active' | 'merged'
  job_id: string
  job_title: string
  candidate_id: string
  candidate_code: string
  candidate_name: string | null
  latest_screening: ReportScreeningEvidence | null
  submitted_evaluations: ReportSubmittedEvaluation[]
  missing_rounds: ReportMissingRound[]
}

export interface InterviewReportContent {
  conclusion: InterviewReportConclusion | null
  executive_summary: string
  strengths: string[]
  concerns: string[]
  follow_up_actions: string[]
}

export interface InterviewReportVersion extends InterviewReportContent {
  id: string
  version_number: number
  source_version_id: string | null
  generation_mode: 'ai' | 'manual'
  screening_result_id: string | null
  evaluation_ids: string[]
  evidence_snapshot: InterviewReportContext
  missing_rounds: ReportMissingRound[]
  model_name: string | null
  prompt_version: string | null
  ai_failure_code: string | null
  ai_failure_message: string | null
  created_by_id: string | null
  created_by_username: string
  created_by_display_name: string
  created_at: string
}

export interface InterviewReportRecord {
  id: string
  application_id: string
  application_status: 'active' | 'merged'
  job_id: string
  job_title: string
  candidate_id: string
  candidate_code: string
  candidate_name: string | null
  status: InterviewReportStatus
  current_version_number: number
  confirmed_by_id: string | null
  confirmed_at: string | null
  created_at: string
  updated_at: string
  versions: InterviewReportVersion[]
}

export interface InterviewReportSummary {
  id: string
  application_id: string
  application_status: 'active' | 'merged'
  candidate_id: string
  candidate_code: string
  candidate_name: string | null
  status: InterviewReportStatus
  current_version_number: number
  current_conclusion: InterviewReportConclusion | null
  confirmed_at: string | null
  updated_at: string
}

export type BatchStatus =
  | 'uploading'
  | 'ready'
  | 'partial_failure'
  | 'failed'
  | 'processing'
  | 'completed'
export type AIInputMode = 'raw' | 'redacted'
export type ResumeDocumentStatus =
  | 'uploaded'
  | 'queued'
  | 'processing'
  | 'completed'
  | 'failed'

export interface ResumeDocumentRecord {
  id: string
  batch_id: string
  original_filename: string
  file_extension: string
  content_type: string
  detected_type: string
  size_bytes: number
  sha256: string | null
  has_original_file: boolean
  extraction_method: string | null
  segment_count: number
  text_character_count: number
  candidate_code: string
  redaction_count: number
  status: ResumeDocumentStatus
  failure_code: string | null
  failure_message: string | null
  attempt_count: number
  processing_attempt_count: number
  processing_started_at: string | null
  parsed_at: string | null
  redacted_at: string | null
  created_at: string
  updated_at: string
}

export interface ResumeTextSegmentRecord {
  id: string
  document_id: string
  segment_key: string
  source_type: 'pdf_page' | 'docx_paragraph' | 'image_ocr'
  source_index: number
  page_number: number | null
  paragraph_index: number | null
  raw_text: string
  normalized_text: string
  redacted_text: string | null
  ocr_confidence: number | null
  sort_order: number
}

export interface ResumeDocumentDetail extends ResumeDocumentRecord {
  text_segments: ResumeTextSegmentRecord[]
}

export interface ScreeningBatchRecord {
  id: string
  job_id: string
  criteria_version_id: string
  criteria_version_number: number
  name: string
  ai_input_mode: AIInputMode
  status: BatchStatus
  total_count: number
  success_count: number
  failed_count: number
  processing_count: number
  created_at: string
  updated_at: string
  documents: ResumeDocumentRecord[]
}

export interface BatchDeletionRecord {
  status: 'deleted' | 'cleanup_pending'
  batch_id: string
  deleted_document_count: number
  deleted_file_count: number
  message: string | null
}

export type AnalysisStatus = 'processing' | 'completed' | 'failed'
export type AIGroup = 'passed' | 'low_match' | 'auto_rejected'
export type RequirementStatus = 'passed' | 'failed' | 'unknown'
export type ManualDecision = 'unprocessed' | 'shortlisted' | 'pending' | 'rejected'
export type DecisionAction = Exclude<ManualDecision, 'unprocessed'>
export type CandidateStage =
  | 'unprocessed'
  | 'pending'
  | 'shortlisted'
  | 'to_contact'
  | 'contacted'
  | 'to_interview'
  | 'completed'
  | 'rejected'

export interface EvidenceCitationRecord {
  id: string
  subject_type: 'profile' | 'hard_requirement' | 'dimension'
  subject_key: string
  segment_key: string
  quote: string
  source_type: 'pdf_page' | 'docx_paragraph' | 'image_ocr'
  page_number: number | null
  paragraph_index: number | null
  sort_order: number
}

export interface HardRequirementJudgmentRecord {
  requirement_id: string
  requirement_type: string
  title: string
  expected_value: string
  auto_reject: boolean
  status: RequirementStatus
  rationale: string
  evidence_segment_keys: string[]
}

export interface DimensionScoreRecord {
  id: string
  scoring_dimension_id: string | null
  dimension_name: string
  score: number
  weight_percent: number
  weighted_score: number
  rationale: string
  missing_items: string[]
  sort_order: number
  evidence: EvidenceCitationRecord[]
}

export interface CandidateProfileRecord {
  id: string
  document_id: string
  version_number: number
  source: 'ai' | 'manual'
  source_profile_id: string | null
  model_name: string
  prompt_version: string
  education: Record<string, unknown>[]
  work_experiences: Record<string, unknown>[]
  projects: Record<string, unknown>[]
  skills: Record<string, unknown>[]
  certifications: Record<string, unknown>[]
  languages: Record<string, unknown>[]
  created_at: string
}

export interface CandidateProfileInput {
  education: Record<string, unknown>[]
  work_experiences: Record<string, unknown>[]
  projects: Record<string, unknown>[]
  skills: Record<string, unknown>[]
  certifications: Record<string, unknown>[]
  languages: Record<string, unknown>[]
}

export interface ReanalysisTaskRecord {
  status: 'queued' | 'enqueue_failed' | 'skipped'
  document_id: string
  criteria_version_id: string
  analysis_version: number
  candidate_profile_id: string | null
  task_id: string | null
  message: string | null
}

export interface CandidateProfileCorrectionRecord {
  profile: CandidateProfileRecord
  reanalysis: ReanalysisTaskRecord
}

export interface BatchReanalysisRecord {
  status: 'queued' | 'partial_failure' | 'enqueue_failed'
  batch_id: string
  criteria_version_id: string
  analysis_version: number
  queued_count: number
  failed_count: number
  skipped_count: number
  tasks: ReanalysisTaskRecord[]
}

export interface RecruiterDecisionRecord {
  id: string
  screening_result_id: string
  sequence_number: number
  previous_decision: ManualDecision
  decision: DecisionAction
  reason: string | null
  is_auto_rejection_override: boolean
  operator_id: string
  operator_display_name: string
  created_at: string
}

export interface ScreeningResultSummary {
  id: string
  batch_id: string
  batch_name: string
  document_id: string
  candidate_code: string
  criteria_version_id: string
  criteria_version_number: number
  analysis_version: number
  status: AnalysisStatus
  ai_group: AIGroup | null
  total_score: number | null
  pass_threshold: number
  current_decision: ManualDecision
  latest_decision_at: string | null
  created_at: string
}

export interface CandidateProcessCardRecord {
  process_id: string | null
  application_id: string
  screening_result_id: string
  batch_id: string
  batch_name: string
  document_id: string
  candidate_code: string
  original_filename: string
  phone: string | null
  ai_group: AIGroup
  total_score: number
  current_decision: ManualDecision
  current_stage: CandidateStage
  stage_entered_at: string
  skills: string[]
  analysis_created_at: string
  interview_evaluation?: InterviewEvaluationProgressRecord | null
}

export type InterviewEvaluationProgressStatus =
  | 'not_started'
  | 'in_progress'
  | 'completed'
  | 'cancelled'

export interface InterviewEvaluationProgressRecord {
  status: InterviewEvaluationProgressStatus
  total_rounds: number
  submitted_count: number
  draft_count: number
  pending_count: number
  cancelled_count: number
  action_round_id: string | null
  action_round_name: string | null
  action_evaluation_status: 'not_started' | 'draft' | 'submitted' | null
}

export interface CandidateProcessTimelineEventRecord {
  event_type: 'decision' | 'stage'
  from_stage: CandidateStage
  to_stage: CandidateStage
  reason: string | null
  operator_id: string | null
  operator_display_name: string
  created_at: string
}

export interface CandidateStageUpdateRecord {
  process_id: string
  document_id: string
  previous_stage: CandidateStage
  current_stage: CandidateStage
  stage_entered_at: string
}

export interface CandidateProcessFilters {
  batchId?: string
  stage?: CandidateStage
  aiGroup?: AIGroup
  minScore?: number
  maxScore?: number
  query?: string
}

export type CandidateRecordStatus = 'active' | 'merged'
export type CandidateListStatus = CandidateRecordStatus | 'all'
export type CandidateDuplicateConfidence = 'strong' | 'weak'
export type CandidateDuplicateReviewStatus = 'pending' | 'not_duplicate' | 'merged'

export interface CandidateSummaryRecord {
  id: string
  candidate_code: string
  full_name: string | null
  phone: string | null
  email: string | null
  status: CandidateRecordStatus
  merged_into_candidate_id: string | null
  application_count: number
  resume_count: number
}

export interface CandidateListItemRecord extends CandidateSummaryRecord {
  pending_duplicate_count: number
  created_at: string
  updated_at: string
}

export interface CandidateListRecord {
  items: CandidateListItemRecord[]
  total: number
  limit: number
  offset: number
}

export interface CandidateApplicationSummaryRecord {
  id: string
  job_id: string
  job_title: string
  job_status: JobStatus
  status: CandidateRecordStatus
  merged_into_application_id: string | null
  current_stage: CandidateStage | null
  document_count: number
  created_at: string
}

export interface CandidateResumeSummaryRecord {
  id: string
  application_id: string | null
  job_id: string
  job_title: string
  batch_id: string
  batch_name: string
  original_filename: string
  status: ResumeDocumentStatus
  created_at: string
}

export interface CandidateDetailRecord extends CandidateListItemRecord {
  applications: CandidateApplicationSummaryRecord[]
  resumes: CandidateResumeSummaryRecord[]
}

export interface CandidateDuplicateReviewRecord {
  id: string
  candidate_a: CandidateSummaryRecord
  candidate_b: CandidateSummaryRecord
  source_document_id: string | null
  confidence: CandidateDuplicateConfidence
  signals: string[]
  status: CandidateDuplicateReviewStatus
  resolved_by_id: string | null
  resolution_note: string | null
  resolved_at: string | null
  created_at: string
  updated_at: string
}

export interface CandidateMergeRecord {
  review: CandidateDuplicateReviewRecord
  target_candidate: CandidateSummaryRecord
  merged_candidate: CandidateSummaryRecord
  moved_application_ids: string[]
  merged_application_ids: string[]
  moved_document_count: number
}

export interface CandidateListFilters {
  status?: CandidateListStatus
  query?: string
  limit?: number
  offset?: number
}

export interface ScreeningResultDetail {
  id: string
  document_id: string
  candidate_code: string
  criteria_version_id: string
  criteria_version_number: number
  analysis_version: number
  status: AnalysisStatus
  ai_group: AIGroup | null
  total_score: number | null
  pass_threshold: number
  hard_requirements: HardRequirementJudgmentRecord[]
  strengths: string[]
  gaps: string[]
  missing_items: string[]
  interview_questions: string[]
  model_name: string
  prompt_version: string
  failure_code: string | null
  failure_message: string | null
  started_at: string
  completed_at: string | null
  created_at: string
  candidate_profile: CandidateProfileRecord | null
  dimension_scores: DimensionScoreRecord[]
  evidence: EvidenceCitationRecord[]
  current_decision: ManualDecision
  decision_history: RecruiterDecisionRecord[]
}

export interface OriginalEvidenceRecord {
  citation_id: string
  segment_key: string
  quote: string
  original_text: string
  source_type: 'pdf_page' | 'docx_paragraph' | 'image_ocr'
  page_number: number | null
  paragraph_index: number | null
}

export interface CandidateComparison {
  job_id: string
  criteria_version_id: string
  criteria_version_number: number
  analysis_version: number
  candidates: ScreeningResultDetail[]
}

export interface ScreeningResultFilters {
  processingStatus?: AnalysisStatus
  aiGroup?: AIGroup
  minScore?: number
  maxScore?: number
  decision?: ManualDecision
}

export const AUTH_UNAUTHORIZED_EVENT = 'smarthr:auth-unauthorized'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  fallbackMessage = '请求失败',
): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, {
    ...init,
    headers,
    credentials: 'include',
  })

  if (!response.ok) {
    if (
      response.status === 401 &&
      path !== '/api/auth/me' &&
      path !== '/api/auth/login'
    ) {
      window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT))
    }
    let message = fallbackMessage
    try {
      const body = (await response.json()) as { detail?: string }
      message = body.detail || fallbackMessage
    } catch {
      // The fallback remains when the server does not return JSON.
    }
    throw new ApiError(response.status, message)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export function fetchLiveHealth(): Promise<HealthResponse> {
  return apiRequest('/api/health/live', {}, '后端服务暂不可用')
}

export async function fetchCurrentUser(): Promise<AuthUser | null> {
  try {
    return await apiRequest<AuthUser>('/api/auth/me', {}, '无法读取登录状态')
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null
    }
    throw error
  }
}

export function login(credentials: LoginCredentials): Promise<AuthUser> {
  return apiRequest<AuthUser>(
    '/api/auth/login',
    {
      method: 'POST',
      body: JSON.stringify(credentials),
    },
    '登录失败，请稍后重试',
  )
}

export function logout(): Promise<void> {
  return apiRequest<void>(
    '/api/auth/logout',
    {
      method: 'POST',
    },
    '退出失败，请稍后重试',
  )
}

export interface ManagedUser {
  id: string
  username: string
  display_name: string
  is_active: boolean
  must_change_password: boolean
  roles: RoleKey[]
  created_at: string
  updated_at: string
}

export interface UserOption {
  id: string
  username: string
  display_name: string
  roles: RoleKey[]
}

export interface UserCreateInput {
  username: string
  display_name: string
  temporary_password: string
  roles: RoleKey[]
}

export interface UserUpdateInput {
  display_name?: string
  is_active?: boolean
  roles?: RoleKey[]
}

export function changePassword(payload: ChangePasswordInput): Promise<AuthUser> {
  return apiRequest<AuthUser>(
    '/api/auth/password',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    '修改密码失败',
  )
}

export function fetchUsers(): Promise<ManagedUser[]> {
  return apiRequest('/api/users', {}, '无法读取用户列表')
}

export function createUser(payload: UserCreateInput): Promise<ManagedUser> {
  return apiRequest(
    '/api/users',
    { method: 'POST', body: JSON.stringify(payload) },
    '创建用户失败',
  )
}

export function updateUser(userId: string, payload: UserUpdateInput): Promise<ManagedUser> {
  return apiRequest(
    `/api/users/${userId}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
    '更新用户失败',
  )
}

export function resetUserPassword(
  userId: string,
  temporaryPassword: string,
): Promise<ManagedUser> {
  return apiRequest(
    `/api/users/${userId}/reset-password`,
    { method: 'POST', body: JSON.stringify({ temporary_password: temporaryPassword }) },
    '重置临时密码失败',
  )
}

export function fetchUserOptions(role: RoleKey): Promise<UserOption[]> {
  return apiRequest(
    `/api/users/options?role=${encodeURIComponent(role)}`,
    {},
    '无法读取负责人选项',
  )
}

export function fetchJobs(includeArchived = false): Promise<JobRecord[]> {
  const query = includeArchived ? '?include_archived=true' : ''
  return apiRequest(`/api/jobs${query}`, {}, '无法读取职位列表')
}

export function fetchJob(jobId: string): Promise<JobDetail> {
  return apiRequest(`/api/jobs/${jobId}`, {}, '无法读取职位详情')
}

export function createJob(payload: JobInput): Promise<JobRecord> {
  return apiRequest(
    '/api/jobs',
    { method: 'POST', body: JSON.stringify(payload) },
    '创建职位失败',
  )
}

export function updateJob(jobId: string, payload: Partial<JobInput>): Promise<JobRecord> {
  return apiRequest(
    `/api/jobs/${jobId}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
    '保存职位失败',
  )
}

export function archiveJob(jobId: string): Promise<JobRecord> {
  return apiRequest(`/api/jobs/${jobId}/archive`, { method: 'POST' }, '归档职位失败')
}

export function fetchRecruitmentRequests(
  status?: RecruitmentRequestStatus,
): Promise<RecruitmentRequestRecord[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  return apiRequest(
    `/api/recruitment-requests${query}`,
    {},
    '无法读取招聘需求列表',
  )
}

export function createRecruitmentRequest(
  payload: RecruitmentRequestCreateInput,
): Promise<RecruitmentRequestRecord> {
  return apiRequest(
    '/api/recruitment-requests',
    { method: 'POST', body: JSON.stringify(payload) },
    '创建招聘需求失败',
  )
}

export function createRecruitmentRequestVersion(
  requestId: string,
  payload: RecruitmentRequestVersionCreateInput,
): Promise<RecruitmentRequestRecord> {
  return apiRequest(
    `/api/recruitment-requests/${requestId}/versions`,
    { method: 'POST', body: JSON.stringify(payload) },
    '保存招聘需求新版本失败',
  )
}

export function submitRecruitmentRequest(
  requestId: string,
  versionId: string,
): Promise<RecruitmentRequestRecord> {
  return apiRequest(
    `/api/recruitment-requests/${requestId}/submit`,
    { method: 'POST', body: JSON.stringify({ version_id: versionId }) },
    '提交招聘需求失败',
  )
}

export function decideRecruitmentRequest(
  requestId: string,
  versionId: string,
  decision: RecruitmentRequestDecision,
  comment: string,
): Promise<RecruitmentRequestRecord> {
  return apiRequest(
    `/api/recruitment-requests/${requestId}/decision`,
    {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId, decision, comment }),
    },
    decision === 'approved' ? '批准招聘需求失败' : '驳回招聘需求失败',
  )
}

export function createJobFromRecruitmentRequest(
  requestId: string,
  payload: RecruitmentRequestJobInput,
): Promise<JobRecord> {
  return apiRequest(
    `/api/recruitment-requests/${requestId}/job`,
    { method: 'POST', body: JSON.stringify(payload) },
    '创建关联职位失败',
  )
}

export function createCriteriaVersion(
  jobId: string,
  sourceVersionId?: string,
): Promise<CriteriaVersion> {
  return apiRequest(
    `/api/jobs/${jobId}/criteria/versions`,
    {
      method: 'POST',
      body: JSON.stringify({ source_version_id: sourceVersionId ?? null }),
    },
    '创建筛选标准版本失败',
  )
}

export function updateCriteriaDraft(
  jobId: string,
  versionId: string,
  payload: CriteriaDraftInput,
): Promise<CriteriaVersion> {
  return apiRequest(
    `/api/jobs/${jobId}/criteria/versions/${versionId}`,
    { method: 'PUT', body: JSON.stringify(payload) },
    '保存筛选标准失败',
  )
}

export function confirmCriteriaVersion(
  jobId: string,
  versionId: string,
): Promise<CriteriaVersion> {
  return apiRequest(
    `/api/jobs/${jobId}/criteria/versions/${versionId}/confirm`,
    { method: 'POST' },
    '确认筛选标准失败',
  )
}

export function generateJDAIDraft(jobId: string): Promise<JDAIDraft> {
  return apiRequest(
    `/api/jobs/${jobId}/criteria/ai-draft`,
    { method: 'POST' },
    'AI 生成筛选草稿失败',
  )
}

export function fetchInterviewPlanVersions(jobId: string): Promise<InterviewPlanVersion[]> {
  return apiRequest(
    `/api/jobs/${jobId}/interview-plans/versions`,
    {},
    '无法读取面试方案版本',
  )
}

export function createInterviewPlanVersion(
  jobId: string,
  sourceVersionId?: string,
): Promise<InterviewPlanVersion> {
  return apiRequest(
    `/api/jobs/${jobId}/interview-plans/versions`,
    {
      method: 'POST',
      body: JSON.stringify({ source_version_id: sourceVersionId ?? null }),
    },
    '创建面试方案版本失败',
  )
}

export function updateInterviewPlanDraft(
  jobId: string,
  versionId: string,
  payload: InterviewPlanDraftInput,
): Promise<InterviewPlanVersion> {
  return apiRequest(
    `/api/jobs/${jobId}/interview-plans/versions/${versionId}`,
    { method: 'PUT', body: JSON.stringify(payload) },
    '保存面试方案失败',
  )
}

export function confirmInterviewPlanVersion(
  jobId: string,
  versionId: string,
): Promise<InterviewPlanVersion> {
  return apiRequest(
    `/api/jobs/${jobId}/interview-plans/versions/${versionId}/confirm`,
    { method: 'POST' },
    '确认面试方案失败',
  )
}

export async function fetchCandidateInterviewSchedule(
  jobId: string,
  documentId: string,
): Promise<InterviewScheduleRecord | null> {
  try {
    return await apiRequest(
      `/api/jobs/${jobId}/candidate-processes/${documentId}/interview-schedule`,
      {},
      '无法读取候选人面试安排',
    )
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

export function createCandidateInterviewSchedule(
  jobId: string,
  documentId: string,
  payload: InterviewScheduleCreateInput,
): Promise<InterviewScheduleRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/candidate-processes/${documentId}/interview-schedule`,
    { method: 'POST', body: JSON.stringify(payload) },
    '创建候选人面试安排失败',
  )
}

export function rescheduleCandidateInterviewRound(
  jobId: string,
  documentId: string,
  roundId: string,
  payload: InterviewRoundRescheduleInput,
): Promise<InterviewScheduleRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/candidate-processes/${documentId}/interview-schedule/rounds/${roundId}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
    '修改候选人面试时间失败',
  )
}

export function cancelCandidateInterviewRound(
  jobId: string,
  documentId: string,
  roundId: string,
  reason: string,
): Promise<InterviewScheduleRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/candidate-processes/${documentId}/interview-schedule/rounds/${roundId}/cancel`,
    { method: 'POST', body: JSON.stringify({ reason }) },
    '取消候选人面试轮次失败',
  )
}

export function fetchInterviewEvaluation(
  jobId: string,
  documentId: string,
  roundId: string,
): Promise<InterviewEvaluationContext> {
  return apiRequest(
    `/api/jobs/${jobId}/candidate-processes/${documentId}/interview-schedule/rounds/${roundId}/evaluation`,
    {},
    '无法读取面试评价',
  )
}

export function saveInterviewEvaluationDraft(
  jobId: string,
  documentId: string,
  roundId: string,
  payload: InterviewEvaluationDraftInput,
): Promise<InterviewEvaluationContext> {
  return apiRequest(
    `/api/jobs/${jobId}/candidate-processes/${documentId}/interview-schedule/rounds/${roundId}/evaluation`,
    { method: 'PUT', body: JSON.stringify(payload) },
    '保存面试评价草稿失败',
  )
}

export function submitInterviewEvaluation(
  jobId: string,
  documentId: string,
  roundId: string,
): Promise<InterviewEvaluationContext> {
  return apiRequest(
    `/api/jobs/${jobId}/candidate-processes/${documentId}/interview-schedule/rounds/${roundId}/evaluation/submit`,
    { method: 'POST' },
    '提交面试评价失败',
  )
}

export function fetchInterviewReports(jobId: string): Promise<InterviewReportSummary[]> {
  return apiRequest(
    `/api/jobs/${jobId}/interview-reports`,
    {},
    '无法读取面试报告列表',
  )
}

export function fetchInterviewReportContext(
  jobId: string,
  applicationId: string,
): Promise<InterviewReportContext> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/interview-report/context`,
    {},
    '无法读取面试报告证据',
  )
}

export async function fetchInterviewReport(
  jobId: string,
  applicationId: string,
): Promise<InterviewReportRecord | null> {
  try {
    return await apiRequest(
      `/api/jobs/${jobId}/applications/${applicationId}/interview-report`,
      {},
      '无法读取面试报告',
    )
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

export function createManualInterviewReport(
  jobId: string,
  applicationId: string,
  idempotencyKey: string,
  content: InterviewReportContent,
): Promise<InterviewReportRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/interview-report/manual-draft`,
    {
      method: 'POST',
      body: JSON.stringify({ idempotency_key: idempotencyKey, ...content }),
    },
    '创建人工面试报告失败',
  )
}

export function generateAIInterviewReport(
  jobId: string,
  applicationId: string,
  idempotencyKey: string,
): Promise<InterviewReportRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/interview-report/ai-draft`,
    {
      method: 'POST',
      body: JSON.stringify({ idempotency_key: idempotencyKey }),
    },
    '生成 AI 面试报告失败',
  )
}

export function createInterviewReportVersion(
  jobId: string,
  applicationId: string,
  idempotencyKey: string,
  sourceVersionId: string,
  content: InterviewReportContent,
): Promise<InterviewReportRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/interview-report/versions`,
    {
      method: 'POST',
      body: JSON.stringify({
        idempotency_key: idempotencyKey,
        source_version_id: sourceVersionId,
        ...content,
      }),
    },
    '保存面试报告新版本失败',
  )
}

export function confirmInterviewReport(
  jobId: string,
  applicationId: string,
  versionId: string,
): Promise<InterviewReportRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/interview-report/confirm`,
    {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId }),
    },
    '确认面试报告失败',
  )
}

export function fetchScreeningBatches(jobId: string): Promise<ScreeningBatchRecord[]> {
  return apiRequest(`/api/jobs/${jobId}/batches`, {}, '无法读取简历批次')
}

export function createScreeningBatch(
  jobId: string,
  criteriaVersionId: string,
  files: File[],
  name = '',
  aiInputMode: AIInputMode = 'raw',
): Promise<ScreeningBatchRecord> {
  const body = new FormData()
  body.append('criteria_version_id', criteriaVersionId)
  body.append('name', name)
  body.append('ai_input_mode', aiInputMode)
  files.forEach((file) => body.append('files', file))
  return apiRequest(
    `/api/jobs/${jobId}/batches`,
    { method: 'POST', body },
    '上传简历批次失败',
  )
}

export function retryResumeDocument(
  jobId: string,
  batchId: string,
  documentId: string,
  file: File,
): Promise<ResumeDocumentRecord> {
  const body = new FormData()
  body.append('file', file)
  return apiRequest(
    `/api/jobs/${jobId}/batches/${batchId}/documents/${documentId}/retry`,
    { method: 'PUT', body },
    '重新上传简历失败',
  )
}

export function retryResumeParsing(
  jobId: string,
  batchId: string,
  documentId: string,
): Promise<ResumeDocumentRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/batches/${batchId}/documents/${documentId}/parse-retry`,
    { method: 'POST' },
    '重新处理简历失败',
  )
}

export function fetchResumeDocumentDetail(
  jobId: string,
  batchId: string,
  documentId: string,
): Promise<ResumeDocumentDetail> {
  return apiRequest(
    `/api/jobs/${jobId}/batches/${batchId}/documents/${documentId}`,
    {},
    '无法读取简历文本',
  )
}

export function deleteScreeningBatch(
  jobId: string,
  batchId: string,
  confirmation: string,
): Promise<BatchDeletionRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/batches/${batchId}`,
    {
      method: 'DELETE',
      body: JSON.stringify({ confirmation }),
    },
    '永久删除简历批次失败',
  )
}

export function resumeFileUrl(jobId: string, batchId: string, documentId: string): string {
  return `/api/jobs/${jobId}/batches/${batchId}/documents/${documentId}/file`
}

export function fetchCandidateProfiles(
  jobId: string,
  batchId: string,
  documentId: string,
): Promise<CandidateProfileRecord[]> {
  return apiRequest(
    `/api/jobs/${jobId}/batches/${batchId}/documents/${documentId}/profiles`,
    {},
    '无法读取候选人资料版本',
  )
}

export function fetchCandidateAnalysisHistory(
  jobId: string,
  batchId: string,
  documentId: string,
): Promise<ScreeningResultDetail[]> {
  return apiRequest(
    `/api/jobs/${jobId}/batches/${batchId}/documents/${documentId}/analysis-history`,
    {},
    '无法读取候选人分析历史',
  )
}

export function correctCandidateProfile(
  jobId: string,
  batchId: string,
  documentId: string,
  sourceProfileId: string,
  criteriaVersionId: string,
  profile: CandidateProfileInput,
): Promise<CandidateProfileCorrectionRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/batches/${batchId}/documents/${documentId}/profile-corrections`,
    {
      method: 'POST',
      body: JSON.stringify({
        source_profile_id: sourceProfileId,
        criteria_version_id: criteriaVersionId,
        ...profile,
      }),
    },
    '修正候选人资料失败',
  )
}

export function reanalyzeCandidate(
  jobId: string,
  batchId: string,
  documentId: string,
  criteriaVersionId: string,
  candidateProfileId?: string,
): Promise<ReanalysisTaskRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/batches/${batchId}/documents/${documentId}/reanalysis`,
    {
      method: 'POST',
      body: JSON.stringify({
        criteria_version_id: criteriaVersionId,
        candidate_profile_id: candidateProfileId,
      }),
    },
    '重新分析候选人失败',
  )
}

export function reanalyzeBatch(
  jobId: string,
  batchId: string,
  criteriaVersionId: string,
): Promise<BatchReanalysisRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/batches/${batchId}/reanalysis`,
    {
      method: 'POST',
      body: JSON.stringify({ criteria_version_id: criteriaVersionId }),
    },
    '整批重新分析失败',
  )
}

export function fetchScreeningResults(
  jobId: string,
  filters: ScreeningResultFilters = {},
): Promise<ScreeningResultSummary[]> {
  const query = new URLSearchParams()
  if (filters.processingStatus) query.set('processing_status', filters.processingStatus)
  if (filters.aiGroup) query.set('ai_group', filters.aiGroup)
  if (filters.minScore !== undefined) query.set('min_score', String(filters.minScore))
  if (filters.maxScore !== undefined) query.set('max_score', String(filters.maxScore))
  if (filters.decision) query.set('decision', filters.decision)
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest(
    `/api/jobs/${jobId}/screening-results${suffix}`,
    {},
    '无法读取筛选结果',
  )
}

export function fetchScreeningResult(
  jobId: string,
  resultId: string,
): Promise<ScreeningResultDetail> {
  return apiRequest(
    `/api/jobs/${jobId}/screening-results/${resultId}`,
    {},
    '无法读取候选人筛选详情',
  )
}

export function fetchCandidateProcesses(
  jobId: string,
  filters: CandidateProcessFilters = {},
): Promise<CandidateProcessCardRecord[]> {
  const query = new URLSearchParams()
  if (filters.batchId) query.set('batch_id', filters.batchId)
  if (filters.stage) query.set('stage', filters.stage)
  if (filters.aiGroup) query.set('ai_group', filters.aiGroup)
  if (filters.minScore !== undefined) query.set('min_score', String(filters.minScore))
  if (filters.maxScore !== undefined) query.set('max_score', String(filters.maxScore))
  if (filters.query?.trim()) query.set('query', filters.query.trim())
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest(
    `/api/jobs/${jobId}/candidate-processes${suffix}`,
    {},
    '无法读取候选人流程看板',
  )
}

export function fetchCandidates(filters: CandidateListFilters = {}): Promise<CandidateListRecord> {
  const query = new URLSearchParams()
  if (filters.status) query.set('status', filters.status)
  if (filters.query?.trim()) query.set('query', filters.query.trim())
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest(`/api/candidates${suffix}`, {}, '无法读取候选人档案')
}

export function fetchCandidate(candidateId: string): Promise<CandidateDetailRecord> {
  return apiRequest(
    `/api/candidates/${encodeURIComponent(candidateId)}`,
    {},
    '无法读取候选人详情',
  )
}

export function fetchCandidateDuplicateReviews(
  status: CandidateDuplicateReviewStatus | 'all' = 'pending',
): Promise<CandidateDuplicateReviewRecord[]> {
  return apiRequest(
    `/api/candidates/duplicate-reviews?status=${encodeURIComponent(status)}`,
    {},
    '无法读取重复候选人提示',
  )
}

export function dismissCandidateDuplicateReview(
  reviewId: string,
  reason: string,
): Promise<CandidateDuplicateReviewRecord> {
  return apiRequest(
    `/api/candidates/duplicate-reviews/${encodeURIComponent(reviewId)}/dismiss`,
    { method: 'POST', body: JSON.stringify({ reason }) },
    '无法保存非重复判定',
  )
}

export function mergeCandidateDuplicateReview(
  reviewId: string,
  targetCandidateId: string,
  reason: string,
): Promise<CandidateMergeRecord> {
  return apiRequest(
    `/api/candidates/duplicate-reviews/${encodeURIComponent(reviewId)}/merge`,
    {
      method: 'POST',
      body: JSON.stringify({ target_candidate_id: targetCandidateId, reason }),
    },
    '无法合并候选人档案',
  )
}

export function updateCandidateStage(
  jobId: string,
  documentId: string,
  expectedStage: CandidateStage,
  targetStage: CandidateStage,
  reason?: string,
): Promise<CandidateStageUpdateRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/candidate-processes/${documentId}/stage`,
    {
      method: 'POST',
      body: JSON.stringify({
        expected_stage: expectedStage,
        target_stage: targetStage,
        reason: reason?.trim() || null,
      }),
    },
    '调整候选人阶段失败',
  )
}

export function fetchCandidateProcessTimeline(
  jobId: string,
  documentId: string,
): Promise<CandidateProcessTimelineEventRecord[]> {
  return apiRequest(
    `/api/jobs/${jobId}/candidate-processes/${documentId}/timeline`,
    {},
    '无法读取候选人流程记录',
  )
}

export function fetchOriginalEvidence(
  jobId: string,
  resultId: string,
  citationId: string,
): Promise<OriginalEvidenceRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/screening-results/${resultId}/evidence/${citationId}`,
    {},
    '无法读取原文证据',
  )
}

export function createRecruiterDecision(
  jobId: string,
  resultId: string,
  decision: DecisionAction,
  reason?: string,
): Promise<RecruiterDecisionRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/screening-results/${resultId}/decisions`,
    {
      method: 'POST',
      body: JSON.stringify({ decision, reason: reason || null }),
    },
    '保存人工结论失败',
  )
}

export function compareScreeningResults(
  jobId: string,
  resultIds: string[],
): Promise<CandidateComparison> {
  return apiRequest(
    `/api/jobs/${jobId}/screening-results/compare`,
    {
      method: 'POST',
      body: JSON.stringify({ result_ids: resultIds }),
    },
    '无法比较候选人',
  )
}
