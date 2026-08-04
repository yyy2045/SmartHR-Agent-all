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

export type WorkbenchSection = 'action_required' | 'waiting_external' | 'risk_failure'
export type WorkbenchPriority = 'urgent' | 'high' | 'normal'
export type WorkbenchItemType =
  | 'recruitment_request_revision'
  | 'recruitment_request_approval'
  | 'manual_screening'
  | 'interview_scheduling'
  | 'interview_evaluation'
  | 'interview_report'
  | 'offer_manager_confirmation'
  | 'offer_approval'
  | 'offer_link'
  | 'onboarding_date'
  | 'onboarding_outcome'
  | 'system_failure'
  | 'temporary_password_account'
export type WorkbenchSource =
  | 'recruitment_requests'
  | 'screening'
  | 'interviews'
  | 'offers'
  | 'onboardings'
  | 'system_failures'
  | 'accounts'

export interface WorkbenchItemRecord {
  stable_key: string
  section: WorkbenchSection
  item_type: WorkbenchItemType
  source: WorkbenchSource
  priority: WorkbenchPriority
  title: string
  summary: string
  count: number
  occurred_at: string
  risk_at: string | null
  job_id: string | null
  job_title: string | null
  target_path: string
}

export interface WorkbenchSummaryRecord {
  as_of: string
  total_count: number
  action_required_count: number
  sections: Array<{ section: WorkbenchSection; count: number }>
  priorities: Array<{ priority: WorkbenchPriority; count: number }>
  types: Array<{ item_type: WorkbenchItemType; count: number }>
  jobs: Array<{ id: string; title: string }>
  partial: boolean
  failed_sources: WorkbenchSource[]
}

export interface WorkbenchListRecord {
  as_of: string
  items: WorkbenchItemRecord[]
  total: number
  page: number
  page_size: number
  partial: boolean
  failed_sources: WorkbenchSource[]
}

export interface WorkbenchFilters {
  section?: WorkbenchSection
  itemType?: WorkbenchItemType
  priority?: WorkbenchPriority
  jobId?: string
  page?: number
  pageSize?: number
}
export type InternalNotificationReadStatus = 'all' | 'unread' | 'read'

export interface InternalNotificationRecord {
  id: string
  notification_type: string
  title: string
  summary: string
  resource_type: string
  resource_id: string
  route_path: string
  read_at: string | null
  created_at: string
}

export interface InternalNotificationListRecord {
  items: InternalNotificationRecord[]
  total: number
  unread_count: number
  limit: number
  offset: number
}

export interface InternalNotificationFilters {
  status?: InternalNotificationReadStatus
  notificationType?: string
  limit?: number
  offset?: number
}

export interface InternalNotificationUnreadCountRecord {
  unread_count: number
}

export interface InternalNotificationReadRecord {
  id: string
  read_at: string
}

export interface InternalNotificationReadAllRecord {
  updated_count: number
  read_at: string
}

export type AiTaskStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'retrying' | 'cancelled'
export type AiCallStatus = 'succeeded' | 'failed'

export interface AiObservabilityCountRecord {
  key: string
  count: number
}

export interface AiObservabilitySummaryRecord {
  task_total: number
  call_total: number
  failed_task_count: number
  failed_call_count: number
  total_input_tokens: number
  total_output_tokens: number
  total_tokens: number
  avg_task_duration_ms: number | null
  avg_call_duration_ms: number | null
  task_status_counts: AiObservabilityCountRecord[]
  call_status_counts: AiObservabilityCountRecord[]
  call_scenario_counts: AiObservabilityCountRecord[]
}

export interface AiTaskRecord {
  id: string
  celery_task_id: string | null
  task_name: string
  scenario: string
  status: AiTaskStatus
  attempt_count: number
  max_retries: number
  resource_type: string | null
  resource_id: string | null
  job_id: string | null
  batch_id: string | null
  document_id: string | null
  application_id: string | null
  candidate_profile_id: string | null
  failure_code: string | null
  failure_message: string | null
  duration_ms: number | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface AiTaskListRecord {
  items: AiTaskRecord[]
  total: number
  limit: number
  offset: number
}

export interface AiCallLogRecord {
  id: string
  task_id: string | null
  scenario: string
  status: AiCallStatus
  model_name: string | null
  prompt_version: string | null
  prompt_template_version_id: string | null
  provider: string
  retry_count: number
  duration_ms: number | null
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  resource_type: string | null
  resource_id: string | null
  job_id: string | null
  batch_id: string | null
  document_id: string | null
  application_id: string | null
  candidate_profile_id: string | null
  failure_code: string | null
  failure_message: string | null
  created_at: string
}

export interface AiCallLogListRecord {
  items: AiCallLogRecord[]
  total: number
  limit: number
  offset: number
}

export interface AiObservabilityFilters {
  status?: string
  scenario?: string
  limit?: number
  offset?: number
}

export type PromptScenario =
  | 'jd_generation'
  | 'resume_analysis'
  | 'resume_analysis_repair'
  | 'interview_report'
  | 'offer_copy'
  | 'candidate_comparison'
  | 'candidate_qa'
export type PromptTemplateStatus = 'active' | 'inactive'
export type PromptVersionStatus = 'draft' | 'published' | 'retired'

export interface PromptTemplateVersionRecord {
  id: string
  template_id: string
  version_number: number
  status: PromptVersionStatus
  source_version_id: string | null
  change_note: string
  system_prompt: string
  user_prompt_template: string
  variables: string[]
  output_schema: Record<string, unknown> | null
  model_parameters: Record<string, unknown>
  created_by_id: string | null
  created_by_username: string
  created_by_display_name: string
  published_by_id: string | null
  published_by_username: string | null
  published_by_display_name: string | null
  published_at: string | null
  created_at: string
}

export interface PromptTemplateRecord {
  id: string
  scenario: PromptScenario
  name: string
  description: string | null
  status: PromptTemplateStatus
  current_version_number: number | null
  resource_version: number
  created_by_id: string | null
  created_by_username: string
  created_by_display_name: string
  created_at: string
  updated_at: string
  versions: PromptTemplateVersionRecord[]
}

export interface PromptTemplateListRecord {
  items: PromptTemplateRecord[]
}

export interface PromptTemplateContentInput {
  changeNote: string
  systemPrompt: string
  userPromptTemplate: string
  variables: string[]
  outputSchema?: Record<string, unknown> | null
  modelParameters?: Record<string, unknown>
}

export interface PromptTemplateCreateInput extends PromptTemplateContentInput {
  scenario: PromptScenario
  name: string
  description?: string | null
  idempotencyKey?: string
}

export interface PromptTemplateVersionCreateInput extends PromptTemplateContentInput {
  sourceVersionId?: string | null
  idempotencyKey?: string
}

export type RecruitmentKnowledgeCategory =
  | 'policy'
  | 'job_standard'
  | 'interview'
  | 'offer'
  | 'compensation'
  | 'communication'
  | 'general'
export type RecruitmentKnowledgeVisibilityScope =
  | 'all_internal'
  | 'recruiter_manager'
  | 'recruiter_only'
  | 'admin_only'

export interface RecruitmentKnowledgeBaseRecord {
  id: string
  name: string
  description: string | null
  status: 'active' | 'inactive'
  resource_version: number
  created_at: string
  updated_at: string
}

export interface RecruitmentKnowledgeBaseListRecord {
  items: RecruitmentKnowledgeBaseRecord[]
}

export interface RecruitmentKnowledgeDocumentRecord {
  id: string
  knowledge_base_id: string
  title: string
  summary: string | null
  category: RecruitmentKnowledgeCategory
  tags: string[]
  visibility_scope: RecruitmentKnowledgeVisibilityScope
  related_job_id: string | null
  status: 'active' | 'archived'
  current_version_number: number | null
  resource_version: number
  created_at: string
  updated_at: string
}

export interface RecruitmentKnowledgeVersionRecord {
  id: string
  document_id: string
  version_number: number
  status: 'draft' | 'published' | 'retired'
  source_type: 'manual' | 'upload'
  source_filename: string | null
  mime_type: string | null
  content_hash: string
  change_note: string
  parser_name: string | null
  parser_version: string | null
  chunk_count: number
  published_at: string | null
  created_at: string
}

export interface RecruitmentKnowledgeCreateRecord {
  document: RecruitmentKnowledgeDocumentRecord
  version: RecruitmentKnowledgeVersionRecord
  chunk_count: number
  embedding_enabled: boolean
  index_task_id: string | null
}

export interface RecruitmentKnowledgeManualInput {
  knowledgeBaseId?: string | null
  title: string
  summary?: string | null
  category: RecruitmentKnowledgeCategory
  tags: string[]
  visibilityScope: RecruitmentKnowledgeVisibilityScope
  changeNote: string
  rawText: string
  idempotencyKey?: string
}

export interface RecruitmentKnowledgeUploadInput {
  knowledgeBaseId?: string | null
  title: string
  summary?: string | null
  category: RecruitmentKnowledgeCategory
  tags: string[]
  visibilityScope: RecruitmentKnowledgeVisibilityScope
  changeNote: string
  file: File
  idempotencyKey?: string
}

export interface RecruitmentKnowledgeRetrievalCitation {
  chunk_id: string
  document_id: string
  document_title: string
  version_number: number
  category: RecruitmentKnowledgeCategory
  heading_path: string[]
  source_locator: string | null
  snippet: string
  score: number
}

export interface RecruitmentKnowledgeRetrievalRecord {
  query_hash: string
  returned_count: number
  filtered_count: number
  citations: RecruitmentKnowledgeRetrievalCitation[]
}

export interface RecruitmentKnowledgeRetrievalInput {
  scenario: string
  query: string
  category?: RecruitmentKnowledgeCategory | null
  tags?: string[]
  limit?: number
}

export type AnalyticsInterval = 'day' | 'week'
export type AnalyticsFunnelStage =
  | 'application_created'
  | 'ai_screening_completed'
  | 'recruiter_shortlisted'
  | 'interview_started'
  | 'interview_passed'
  | 'offer_approved'
  | 'offer_accepted'
  | 'onboarding_completed'
export type AnalyticsCurrentStage =
  | 'unprocessed'
  | 'pending'
  | 'shortlisted'
  | 'to_contact'
  | 'contacted'
  | 'to_interview'
  | 'completed'
  | 'rejected'
  | 'offer_pending_response'
  | 'offer_rejected'
  | 'onboarding_pending_confirmation'
  | 'onboarding_pending_start'
  | 'onboarding_completed'
  | 'onboarding_abandoned'
export type AnalyticsOfferStatus = OfferStatus
export type AnalyticsOnboardingStatus = OnboardingStatus
export type AnalyticsDecisionDifference =
  | 'consistent'
  | 'human_upgraded'
  | 'human_downgraded'
  | 'missing_human_decision'

export interface AnalyticsQueryRecord {
  start_date: string
  end_date: string
  job_id: string | null
}

export interface AnalyticsMetaRecord {
  as_of: string
  timezone: 'Asia/Shanghai'
  query: AnalyticsQueryRecord
  visible_job_count: number
}

export interface AnalyticsQualityRecord {
  complete: boolean
  excluded_count: number
  reasons: string[]
}

export interface AnalyticsRatioMetricRecord {
  key: string
  label: string
  numerator: number
  denominator: number
  percentage: number | null
  small_sample: boolean
}

export interface AnalyticsDashboardRecord {
  meta: AnalyticsMetaRecord
  jobs: Array<{ id: string; title: string; status: JobStatus }>
  overview: {
    meta: AnalyticsMetaRecord
    quality: AnalyticsQualityRecord
    active_job_count: number
    selected_job_count: number
    application_count: number
    unique_candidate_count: number
    approved_headcount: number
    hired_count: number
    linked_hired_count: number
    hiring_completion_rate: AnalyticsRatioMetricRecord
  }
  funnel: {
    meta: AnalyticsMetaRecord
    quality: AnalyticsQualityRecord
    cohort_size: number
    stages: Array<{
      key: AnalyticsFunnelStage
      label: string
      count: number
      cohort_percentage: number | null
    }>
  }
  current_distribution: {
    meta: AnalyticsMetaRecord
    quality: AnalyticsQualityRecord
    total: number
    stages: Array<{ key: AnalyticsCurrentStage; label: string; count: number }>
  }
  trend: {
    meta: AnalyticsMetaRecord
    quality: AnalyticsQualityRecord
    interval: AnalyticsInterval
    points: Array<{
      bucket_start: string
      bucket_end: string
      applications_created: number
      offers_accepted: number
      onboardings_completed: number
    }>
  }
  stage_duration: {
    meta: AnalyticsMetaRecord
    quality: AnalyticsQualityRecord
    stages: Array<{
      stage: AnalyticsFunnelStage
      label: string
      sample_size: number
      p50_seconds: number | null
      p90_seconds: number | null
      excluded_count: number
      current_open_count: number
    }>
  }
  interviews: {
    meta: AnalyticsMetaRecord
    quality: AnalyticsQualityRecord
    round_pass_rate: AnalyticsRatioMetricRecord
    candidate_pass_rate: AnalyticsRatioMetricRecord
  }
  offers: {
    meta: AnalyticsMetaRecord
    quality: AnalyticsQualityRecord
    total_offers: number
    statuses: Array<{ key: AnalyticsOfferStatus; label: string; count: number }>
    acceptance_rate: AnalyticsRatioMetricRecord
  }
  onboardings: {
    meta: AnalyticsMetaRecord
    quality: AnalyticsQualityRecord
    total_records: number
    statuses: Array<{ key: AnalyticsOnboardingStatus; label: string; count: number }>
    completion_rate: AnalyticsRatioMetricRecord
    abandonment_sources: Array<{
      key: OnboardingAbandonmentSource
      label: string
      count: number
    }>
  }
  decision_difference: {
    meta: AnalyticsMetaRecord
    quality: AnalyticsQualityRecord
    ai_screened_count: number
    categories: Array<{
      key: AnalyticsDecisionDifference
      label: string
      count: number
      percentage: number | null
    }>
  }
}

export interface AnalyticsFilters {
  startDate?: string
  endDate?: string
  jobId?: string
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

export type OfferStatus =
  | 'draft'
  | 'pending_manager_confirmation'
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'pending_response'
  | 'accepted'
  | 'declined'

export type OfferPortalLinkState = 'active' | 'expired' | 'revoked' | 'responded'
export type CandidateOfferDecision = 'accepted' | 'rejected'
export type CandidateOfferProgress = 'offer_pending_response' | 'accepted' | 'declined'
export type CandidateOfferRejectionReason =
  | 'compensation'
  | 'career'
  | 'location'
  | 'timing'
  | 'other'

export interface OfferPortalLinkRecord {
  id: string
  version_id: string
  state: OfferPortalLinkState
  expires_at: string
  created_by_username: string
  created_by_display_name: string
  created_at: string
  revoked_at: string | null
  revoked_by_username: string | null
  revoked_by_display_name: string | null
  revocation_reason: string | null
}

export interface OfferPortalLinkIssuedRecord extends OfferPortalLinkRecord {
  portal_token: string | null
}

export interface CandidateOfferResponseRecord {
  decision: CandidateOfferDecision
  rejection_reason_code: CandidateOfferRejectionReason | null
  rejection_note: string | null
  responded_at: string
}

export interface CandidateOfferViewRecord {
  candidate_name: string | null
  job_title: string
  progress: CandidateOfferProgress
  currency: 'CNY'
  monthly_salary: string
  annual_salary_months: string
  probation_months: number
  probation_monthly_salary: string | null
  bonus_description: string
  expected_start_date: string
  valid_until: string
  notes: string
  response: CandidateOfferResponseRecord | null
  onboarding: CandidateOnboardingRecord | null
}

export type OnboardingStatus =
  | 'pending_confirmation'
  | 'candidate_proposed_date'
  | 'pending_start'
  | 'onboarded'
  | 'abandoned'
export type OnboardingActionOwner = 'candidate' | 'recruiter' | 'none'
export type OnboardingAbandonmentSource =
  | 'candidate_withdrew'
  | 'company_cancelled'
  | 'other'
export type OnboardingAbandonmentReason =
  | 'compensation'
  | 'career'
  | 'location'
  | 'start_date'
  | 'personal'
  | 'position_cancelled'
  | 'business_change'
  | 'other'
export type OnboardingEventAction =
  | 'created'
  | 'candidate_confirmed_date'
  | 'candidate_proposed_date'
  | 'recruiter_accepted_date'
  | 'recruiter_proposed_date'
  | 'onboarded'
  | 'abandoned'
  | 'onboarded_corrected'

export interface CandidateOnboardingRecord {
  status: OnboardingStatus
  version: number
  action_owner: OnboardingActionOwner
  expected_start_date: string
  candidate_proposed_date: string | null
  recruiter_proposed_date: string | null
  confirmed_start_date: string | null
  actual_start_date: string | null
  abandonment_source: OnboardingAbandonmentSource | null
  abandonment_reason_code: OnboardingAbandonmentReason | null
}

export interface OfferOnboardingSummaryRecord {
  id: string
  status: OnboardingStatus
  version: number
  action_owner: OnboardingActionOwner
  expected_start_date: string
  candidate_proposed_date: string | null
  recruiter_proposed_date: string | null
  confirmed_start_date: string | null
  actual_start_date: string | null
}

export interface OnboardingEventRecord {
  id: string
  sequence_number: number
  action: OnboardingEventAction
  from_status: OnboardingStatus | null
  to_status: OnboardingStatus
  date_before: string | null
  date_after: string | null
  reason: string | null
  actor_type: 'system' | 'candidate' | 'recruiter' | 'admin'
  actor_username: string | null
  actor_display_name: string | null
  created_at: string
}

export interface OnboardingSummaryRecord extends CandidateOnboardingRecord {
  id: string
  application_id: string
  offer_id: string
  job_id: string
  job_title: string
  job_status: 'active' | 'archived'
  recruiter_available: boolean
  candidate_id: string
  candidate_code: string
  candidate_name: string | null
  candidate_phone: string | null
  start_date_overdue: boolean
  updated_at: string
}

export interface OnboardingDetailRecord extends OnboardingSummaryRecord {
  abandonment_note: string | null
  events: OnboardingEventRecord[]
}

export interface OnboardingListRecord {
  items: OnboardingSummaryRecord[]
  total: number
  page: number
  page_size: number
}

export interface OfferPortalVerifiedRecord extends CandidateOfferViewRecord {
  verification_token: string
  verification_expires_at: string
}

export interface OfferPortalStatusRecord {
  status: 'verification_required'
}

export interface OfferContentInput {
  monthly_salary: number
  annual_salary_months: number
  probation_months: number
  probation_monthly_salary: number | null
  bonus_description: string
  expected_start_date: string
  valid_until: string
  notes: string
}

export interface OfferManagerConfirmation {
  id: string
  idempotency_key: string
  confirmer_id: string | null
  confirmer_username: string
  confirmer_display_name: string
  decision: 'confirmed' | 'rejected'
  comment: string
  decided_at: string
}

export interface OfferApproval {
  id: string
  idempotency_key: string
  approver_id: string | null
  approver_username: string
  approver_display_name: string
  decision: 'approved' | 'rejected'
  comment: string
  decided_at: string
}

export interface OfferVersion {
  id: string
  version_number: number
  idempotency_key: string
  submission_idempotency_key: string | null
  submitted_at: string | null
  source_version_id: string | null
  source_interview_report_version_id: string | null
  currency: 'CNY'
  monthly_salary: string
  annual_salary_months: string
  probation_months: number
  probation_monthly_salary: string | null
  bonus_description: string
  expected_start_date: string
  valid_until: string
  notes: string
  created_by_id: string | null
  created_by_username: string
  created_by_display_name: string
  created_at: string
  manager_confirmation: OfferManagerConfirmation | null
  approval: OfferApproval | null
}

export interface OfferRecord {
  id: string
  application_id: string
  application_status: 'active' | 'merged'
  job_id: string
  job_title: string
  candidate_id: string
  candidate_code: string
  candidate_name: string | null
  status: OfferStatus
  current_version_number: number
  current_version: OfferVersion
  versions: OfferVersion[]
  created_by_id: string | null
  created_at: string
  updated_at: string
  onboarding: OfferOnboardingSummaryRecord | null
}

export interface OfferSummary {
  id: string
  application_id: string
  job_id: string
  job_title: string
  candidate_id: string
  candidate_code: string
  candidate_name: string | null
  status: OfferStatus
  current_version_number: number
  current_version: OfferVersion
  updated_at: string
}

export type MessageTemplateType =
  | 'interview_invitation'
  | 'interview_reschedule'
  | 'interview_cancellation'
  | 'meeting_details'
  | 'offer_notification'
  | 'offer_reminder'
  | 'onboarding_date_confirmation'
export type MessageTemplateStatus = 'active' | 'inactive' | 'all'
export type CommunicationContextType = 'interview_round' | 'offer' | 'onboarding'
export type CommunicationChannel = 'wechat' | 'phone' | 'sms' | 'email' | 'other'
export type CommunicationRecordKind = 'sent' | 'correction'
export type CommunicationAction = 'copy' | 'record_send' | 'correct'

export interface MessageTemplateVersionRecord {
  id: string
  version_number: number
  source_version_id: string | null
  subject: string
  body: string
  variables: string[]
  created_by_id: string | null
  created_by_username: string
  created_by_display_name: string
  created_at: string
}

export interface MessageTemplateSummaryRecord {
  id: string
  system_key: string | null
  template_type: MessageTemplateType
  name: string
  status: Exclude<MessageTemplateStatus, 'all'>
  current_version_number: number
  resource_version: number
  current_subject: string
  updated_at: string
  allowed_actions: string[]
}

export interface MessageTemplateRecord extends MessageTemplateSummaryRecord {
  created_by_id: string | null
  created_by_username: string
  created_by_display_name: string
  created_at: string
  current_version: MessageTemplateVersionRecord
  versions: MessageTemplateVersionRecord[]
}

export interface MessageTemplateListRecord {
  items: MessageTemplateSummaryRecord[]
  total: number
  limit: number
  offset: number
}

export interface MessageTemplateFilters {
  status?: MessageTemplateStatus
  templateType?: MessageTemplateType
  query?: string
  limit?: number
  offset?: number
}

export interface MessageTemplateContentInput {
  subject: string
  body: string
  variables: string[]
}

export interface MessageTemplateCreateInput extends MessageTemplateContentInput {
  templateType: MessageTemplateType
  name: string
  idempotencyKey?: string
}

export interface MessageTemplateVersionCreateInput extends MessageTemplateContentInput {
  expectedVersion: number
  idempotencyKey?: string
}

export interface MessageTemplateStatusInput {
  expectedVersion: number
  idempotencyKey?: string
}

export interface CommunicationPreviewRecord {
  template_id: string
  template_version_id: string
  template_type: MessageTemplateType
  context_type: CommunicationContextType
  context_id: string
  subject: string
  body: string
  variables_used: string[]
  resolved_variables: Record<string, string>
  missing_optional_variables: string[]
}

export interface CommunicationCopyAuditRecord {
  audit_id: string
  context_type: CommunicationContextType
  context_id: string
  template_version_id: string | null
  copied_at: string
}

export interface CommunicationRecordSummaryRecord {
  id: string
  application_id: string
  candidate_id: string
  job_id: string
  context_type: CommunicationContextType
  context_id: string
  record_kind: CommunicationRecordKind
  channel: CommunicationChannel
  channel_detail: string | null
  recipient_masked: string
  candidate_name_snapshot: string
  subject_snapshot: string
  sent_at: string
  correction_count: number
  latest_correction_id: string | null
  allowed_actions: CommunicationAction[]
}

export interface CommunicationRecordDetailRecord extends CommunicationRecordSummaryRecord {
  template_version_id: string | null
  root_record_id: string | null
  corrects_record_id: string | null
  correction_sequence: number
  correction_reason: string | null
  recipient_type: 'phone' | 'email' | 'other'
  body_snapshot: string
  is_historical: boolean
  historical_note: string | null
  created_by_id: string | null
  created_by_username: string
  created_by_display_name: string
  created_at: string
  corrections: CommunicationRecordDetailRecord[]
}

export interface CommunicationRecordListRecord {
  items: CommunicationRecordSummaryRecord[]
  total: number
  limit: number
  offset: number
}

export interface CommunicationRecordFilters {
  contextType?: CommunicationContextType
  contextId?: string
  applicationId?: string
  limit?: number
  offset?: number
}

export interface CommunicationPreviewInput {
  templateVersionId: string
  contextType: CommunicationContextType
  contextId: string
  subjectOverride?: string | null
  bodyOverride?: string | null
}

export interface CommunicationCopyAuditInput {
  contextType: CommunicationContextType
  contextId: string
  templateVersionId?: string | null
  subject: string
  body: string
  idempotencyKey?: string
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
  retained_document_count: number
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
  | 'offer_pending_response'
  | 'offer_rejected'
  | 'onboarding_pending_confirmation'
  | 'onboarding_pending_start'
  | 'onboarding_completed'
  | 'onboarding_abandoned'

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
  batch_id: string | null
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
  batch_id: string | null
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
  onboarding: CandidateProcessOnboardingRecord | null
}

export interface CandidateProcessOnboardingRecord {
  id: string
  status: OnboardingStatus
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
  batch_id: string | null
  batch_name: string
  original_filename: string
  status: ResumeDocumentStatus
  created_at: string
}

export interface CandidateDetailRecord extends CandidateListItemRecord {
  applications: CandidateApplicationSummaryRecord[]
  resumes: CandidateResumeSummaryRecord[]
}

export interface CandidatePhoneUpdateRecord {
  candidate_id: string
  phone: string
  revoked_portal_link_count: number
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

export type TalentPoolGroupStatus = 'active' | 'archived' | 'all'
export type TalentPoolMembershipStatus = 'active' | 'removed' | 'all'

export interface TalentPoolGroupRecord {
  id: string
  name: string
  description: string | null
  version: number
  is_archived: boolean
  member_count: number
  created_by_id: string | null
  created_by_display_name: string | null
  archived_at: string | null
  archived_by_id: string | null
  archived_by_display_name: string | null
  created_at: string
  updated_at: string
}

export interface TalentPoolGroupListRecord {
  items: TalentPoolGroupRecord[]
  total: number
  limit: number
  offset: number
}

export interface TalentPoolMembershipRecord {
  id: string
  group_id: string
  group_name: string
  group_archived: boolean
  candidate_id: string
  candidate_code: string
  candidate_name: string | null
  phone: string | null
  email: string | null
  status: 'active' | 'removed'
  reason: string
  source_application_id: string | null
  version: number
  joined_at: string
  removed_at: string | null
  updated_at: string
}

export interface TalentPoolMembershipListRecord {
  items: TalentPoolMembershipRecord[]
  total: number
  limit: number
  offset: number
}

export interface TalentPoolMembershipOperationRecord {
  group_id: string
  group_version: number
  items: Array<{
    requested_candidate_id: string
    candidate_id: string
    membership_id: string | null
    status:
      | 'added'
      | 'reactivated'
      | 'already_active'
      | 'removed'
      | 'already_removed'
      | 'not_member'
  }>
}

export type TalentRecommendationRunStatus =
  | 'queued'
  | 'retrieving'
  | 'rescoring'
  | 'completed'
  | 'partial'
  | 'failed'
  | 'cancelled'
export type TalentRecommendationResultStatus =
  | 'retrieved'
  | 'rescoring'
  | 'completed'
  | 'failed'
  | 'excluded'
export type TalentRecommendationAction =
  | 'cancel'
  | 'retry_failed_items'
  | 'select_candidates'

export interface TalentRecommendationRunRecord {
  id: string
  job_id: string
  job_title: string
  criteria_version_id: string
  criteria_version_number: number
  created_by_id: string | null
  created_by_username: string
  created_by_display_name: string
  status: TalentRecommendationRunStatus
  ai_input_mode: 'raw' | 'redacted'
  recall_limit: number
  rescore_limit: number
  scope_candidate_count: number
  retrieved_count: number
  rescored_count: number
  completed_count: number
  failed_count: number
  excluded_count: number
  criteria_stale: boolean
  criteria_stale_at: string | null
  failure_code: string | null
  failure_summary: string | null
  resource_version: number
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
  groups: Array<{ group_id: string; group_name: string; group_version: number }>
  allowed_actions: TalentRecommendationAction[]
}

export interface TalentRecommendationResultRecord {
  id: string
  candidate_id: string
  resolved_candidate_id: string
  candidate_code: string
  candidate_name: string | null
  candidate_merged_at: string | null
  document_id: string
  candidate_profile_id: string
  profile_version: number
  vector_rank: number
  similarity_score: number
  matched_group_ids: string[]
  matched_chunks: Array<Record<string, unknown>>
  status: TalentRecommendationResultStatus
  ai_score: number | null
  ai_group: 'passed' | 'low_match' | 'auto_rejected' | null
  ai_dimension_scores: Array<Record<string, unknown>>
  ai_hard_requirement_results: Array<Record<string, unknown>>
  ai_strengths: string[]
  ai_gaps: string[]
  ai_missing_items: string[]
  ai_interview_questions: string[]
  ai_evidence: Array<Record<string, unknown>>
  processing_attempt_count: number
  failure_code: string | null
  failure_message: string | null
  exclusion_code: string | null
  exclusion_reason: string | null
  document_stale: boolean
  profile_stale: boolean
  embedding_stale: boolean
  stale_at: string | null
  completed_at: string | null
}

export interface TalentRecommendationRunDetailRecord
  extends TalentRecommendationRunRecord {
  results: TalentRecommendationResultRecord[]
}

export interface TalentRecommendationRunListRecord {
  items: TalentRecommendationRunRecord[]
  total: number
  limit: number
  offset: number
}

export interface TalentRecommendationSelectionRecord {
  created_count: number
  existing_count: number
  failed_count: number
  items: Array<{
    result_id: string
    status: 'created' | 'existing' | 'failed'
    application_id: string | null
    screening_result_id: string | null
    failure_code: string | null
    failure_message: string | null
  }>
}

export interface TalentRecommendationCreateRecord {
  run: TalentRecommendationRunRecord
  replayed: boolean
  reused_active_run: boolean
}

export interface TalentRecommendationFilters {
  status?: TalentRecommendationRunStatus
  createdById?: string
  createdFrom?: string
  createdTo?: string
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
  notifyUnauthorized = true,
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
      notifyUnauthorized &&
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

export function fetchWorkbenchSummary(): Promise<WorkbenchSummaryRecord> {
  return apiRequest('/api/workbench/summary', {}, '无法读取工作台摘要')
}

export function fetchWorkbenchItems(
  filters: WorkbenchFilters = {},
): Promise<WorkbenchListRecord> {
  const query = new URLSearchParams()
  if (filters.section) query.set('section', filters.section)
  if (filters.itemType) query.set('item_type', filters.itemType)
  if (filters.priority) query.set('priority', filters.priority)
  if (filters.jobId) query.set('job_id', filters.jobId)
  if (filters.page !== undefined) query.set('page', String(filters.page))
  if (filters.pageSize !== undefined) query.set('page_size', String(filters.pageSize))
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest(`/api/workbench/items${suffix}`, {}, '无法读取工作台待办')
}
export function fetchInternalNotifications(
  filters: InternalNotificationFilters = {},
): Promise<InternalNotificationListRecord> {
  const query = new URLSearchParams()
  if (filters.status && filters.status !== 'all') query.set('status', filters.status)
  if (filters.notificationType) query.set('notification_type', filters.notificationType)
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest(`/api/notifications${suffix}`, {}, '无法读取站内通知')
}

export function fetchInternalNotificationUnreadCount(): Promise<InternalNotificationUnreadCountRecord> {
  return apiRequest('/api/notifications/unread-count', {}, '无法读取未读通知数量')
}

export function markInternalNotificationRead(
  notificationId: string,
): Promise<InternalNotificationReadRecord> {
  return apiRequest(
    `/api/notifications/${notificationId}/read`,
    { method: 'POST' },
    '标记通知已读失败',
  )
}

export function markAllInternalNotificationsRead(): Promise<InternalNotificationReadAllRecord> {
  return apiRequest(
    '/api/notifications/read-all',
    { method: 'POST' },
    '全部标记已读失败',
  )
}

export function fetchAIObservabilitySummary(): Promise<AiObservabilitySummaryRecord> {
  return apiRequest('/api/ai-observability/summary', {}, '无法读取 AI 可观测摘要')
}

function buildAIObservabilityQuery(filters: AiObservabilityFilters = {}): string {
  const query = new URLSearchParams()
  if (filters.status) query.set('status', filters.status)
  if (filters.scenario?.trim()) query.set('scenario', filters.scenario.trim())
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  return query.size ? `?${query.toString()}` : ''
}

export function fetchAIObservabilityTasks(
  filters: AiObservabilityFilters = {},
): Promise<AiTaskListRecord> {
  return apiRequest(
    `/api/ai-observability/tasks${buildAIObservabilityQuery(filters)}`,
    {},
    '无法读取 AI 任务中心',
  )
}

export function fetchAIObservabilityCalls(
  filters: AiObservabilityFilters = {},
): Promise<AiCallLogListRecord> {
  return apiRequest(
    `/api/ai-observability/calls${buildAIObservabilityQuery(filters)}`,
    {},
    '无法读取 AI 调用日志',
  )
}

export function fetchPromptTemplates(): Promise<PromptTemplateListRecord> {
  return apiRequest('/api/prompt-templates', {}, '无法读取 Prompt 模板')
}

export function fetchPromptTemplate(templateId: string): Promise<PromptTemplateRecord> {
  return apiRequest(
    `/api/prompt-templates/${encodeURIComponent(templateId)}`,
    {},
    '无法读取 Prompt 模板详情',
  )
}

function promptContentBody(input: PromptTemplateContentInput) {
  return {
    change_note: input.changeNote,
    system_prompt: input.systemPrompt,
    user_prompt_template: input.userPromptTemplate,
    variables: input.variables,
    output_schema: input.outputSchema ?? null,
    model_parameters: input.modelParameters ?? {},
  }
}

export function createPromptTemplate(
  input: PromptTemplateCreateInput,
): Promise<PromptTemplateRecord> {
  return apiRequest(
    '/api/prompt-templates',
    {
      method: 'POST',
      body: JSON.stringify({
        scenario: input.scenario,
        name: input.name,
        description: input.description ?? null,
        ...promptContentBody(input),
        idempotency_key: input.idempotencyKey ?? crypto.randomUUID(),
      }),
    },
    '创建 Prompt 模板失败',
  )
}

export function createPromptTemplateVersion(
  templateId: string,
  input: PromptTemplateVersionCreateInput,
): Promise<PromptTemplateRecord> {
  return apiRequest(
    `/api/prompt-templates/${encodeURIComponent(templateId)}/versions`,
    {
      method: 'POST',
      body: JSON.stringify({
        source_version_id: input.sourceVersionId ?? null,
        ...promptContentBody(input),
        idempotency_key: input.idempotencyKey ?? crypto.randomUUID(),
      }),
    },
    '保存 Prompt 新版本失败',
  )
}

export function publishPromptTemplateVersion(
  templateId: string,
  versionId: string,
  expectedVersion: number,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<PromptTemplateRecord> {
  return apiRequest(
    `/api/prompt-templates/${encodeURIComponent(templateId)}/publish`,
    {
      method: 'POST',
      body: JSON.stringify({
        version_id: versionId,
        expected_version: expectedVersion,
        idempotency_key: idempotencyKey,
      }),
    },
    '发布 Prompt 版本失败',
  )
}

export function fetchRecruitmentKnowledgeBases(): Promise<RecruitmentKnowledgeBaseListRecord> {
  return apiRequest('/api/recruitment-knowledge/bases', {}, '无法读取企业知识库')
}

export function createRecruitmentKnowledgeManual(
  input: RecruitmentKnowledgeManualInput,
): Promise<RecruitmentKnowledgeCreateRecord> {
  return apiRequest(
    '/api/recruitment-knowledge/documents/manual',
    {
      method: 'POST',
      body: JSON.stringify({
        knowledge_base_id: input.knowledgeBaseId ?? null,
        title: input.title,
        summary: input.summary ?? null,
        category: input.category,
        tags: input.tags,
        visibility_scope: input.visibilityScope,
        change_note: input.changeNote,
        raw_text: input.rawText,
        idempotency_key: input.idempotencyKey ?? crypto.randomUUID(),
      }),
    },
    '保存企业知识文档失败',
  )
}

export function uploadRecruitmentKnowledgeDocument(
  input: RecruitmentKnowledgeUploadInput,
): Promise<RecruitmentKnowledgeCreateRecord> {
  const body = new FormData()
  body.append('idempotency_key', input.idempotencyKey ?? crypto.randomUUID())
  body.append('title', input.title)
  body.append('category', input.category)
  body.append('change_note', input.changeNote)
  body.append('visibility_scope', input.visibilityScope)
  if (input.knowledgeBaseId) body.append('knowledge_base_id', input.knowledgeBaseId)
  if (input.summary) body.append('summary', input.summary)
  input.tags.forEach((tag) => body.append('tags', tag))
  body.append('file', input.file)
  return apiRequest(
    '/api/recruitment-knowledge/documents/upload',
    { method: 'POST', body },
    '上传企业知识文档失败',
  )
}

export function retrieveRecruitmentKnowledge(
  input: RecruitmentKnowledgeRetrievalInput,
): Promise<RecruitmentKnowledgeRetrievalRecord> {
  return apiRequest(
    '/api/recruitment-knowledge/retrieve',
    {
      method: 'POST',
      body: JSON.stringify({
        scenario: input.scenario,
        query: input.query,
        category: input.category ?? null,
        tags: input.tags ?? [],
        limit: input.limit ?? 5,
      }),
    },
    '检索企业知识库失败',
  )
}

export function fetchAnalyticsDashboard(
  filters: AnalyticsFilters = {},
): Promise<AnalyticsDashboardRecord> {
  const query = new URLSearchParams()
  if (filters.startDate) query.set('start_date', filters.startDate)
  if (filters.endDate) query.set('end_date', filters.endDate)
  if (filters.jobId) query.set('job_id', filters.jobId)
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest(`/api/analytics/dashboard${suffix}`, {}, '无法读取招聘分析数据')
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
  applicationId: string,
): Promise<InterviewScheduleRecord | null> {
  try {
    return await apiRequest(
      `/api/jobs/${jobId}/applications/${applicationId}/interview-schedule`,
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
  applicationId: string,
  payload: InterviewScheduleCreateInput,
): Promise<InterviewScheduleRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/interview-schedule`,
    { method: 'POST', body: JSON.stringify(payload) },
    '创建候选人面试安排失败',
  )
}

export function rescheduleCandidateInterviewRound(
  jobId: string,
  applicationId: string,
  roundId: string,
  payload: InterviewRoundRescheduleInput,
): Promise<InterviewScheduleRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/interview-schedule/rounds/${roundId}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
    '修改候选人面试时间失败',
  )
}

export function cancelCandidateInterviewRound(
  jobId: string,
  applicationId: string,
  roundId: string,
  reason: string,
): Promise<InterviewScheduleRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/interview-schedule/rounds/${roundId}/cancel`,
    { method: 'POST', body: JSON.stringify({ reason }) },
    '取消候选人面试轮次失败',
  )
}

export function fetchInterviewEvaluation(
  jobId: string,
  applicationId: string,
  roundId: string,
): Promise<InterviewEvaluationContext> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/interview-schedule/rounds/${roundId}/evaluation`,
    {},
    '无法读取面试评价',
  )
}

export function saveInterviewEvaluationDraft(
  jobId: string,
  applicationId: string,
  roundId: string,
  payload: InterviewEvaluationDraftInput,
): Promise<InterviewEvaluationContext> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/interview-schedule/rounds/${roundId}/evaluation`,
    { method: 'PUT', body: JSON.stringify(payload) },
    '保存面试评价草稿失败',
  )
}

export function submitInterviewEvaluation(
  jobId: string,
  applicationId: string,
  roundId: string,
): Promise<InterviewEvaluationContext> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/interview-schedule/rounds/${roundId}/evaluation/submit`,
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

export function fetchMessageTemplates(
  filters: MessageTemplateFilters = {},
): Promise<MessageTemplateListRecord> {
  const query = new URLSearchParams()
  if (filters.status) query.set('status', filters.status)
  if (filters.templateType) query.set('template_type', filters.templateType)
  if (filters.query) query.set('query', filters.query)
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest(`/api/message-templates${suffix}`, {}, '\u65e0\u6cd5\u8bfb\u53d6\u6c9f\u901a\u6a21\u677f')
}

export function fetchMessageTemplate(templateId: string): Promise<MessageTemplateRecord> {
  return apiRequest(`/api/message-templates/${templateId}`, {}, '\u65e0\u6cd5\u8bfb\u53d6\u6a21\u677f\u8be6\u60c5')
}

export function createMessageTemplate(
  input: MessageTemplateCreateInput,
): Promise<MessageTemplateRecord> {
  return apiRequest(
    '/api/message-templates',
    {
      method: 'POST',
      body: JSON.stringify({
        template_type: input.templateType,
        name: input.name,
        subject: input.subject,
        body: input.body,
        variables: input.variables,
        idempotency_key: input.idempotencyKey ?? crypto.randomUUID(),
      }),
    },
    '创建沟通模板失败',
  )
}

export function createMessageTemplateVersion(
  templateId: string,
  input: MessageTemplateVersionCreateInput,
): Promise<MessageTemplateRecord> {
  return apiRequest(
    `/api/message-templates/${templateId}/versions`,
    {
      method: 'POST',
      body: JSON.stringify({
        expected_version: input.expectedVersion,
        subject: input.subject,
        body: input.body,
        variables: input.variables,
        idempotency_key: input.idempotencyKey ?? crypto.randomUUID(),
      }),
    },
    '保存沟通模板新版本失败',
  )
}

export function activateMessageTemplate(
  templateId: string,
  input: MessageTemplateStatusInput,
): Promise<MessageTemplateRecord> {
  return apiRequest(
    `/api/message-templates/${templateId}/activate`,
    {
      method: 'POST',
      body: JSON.stringify({
        expected_version: input.expectedVersion,
        idempotency_key: input.idempotencyKey ?? crypto.randomUUID(),
      }),
    },
    '启用沟通模板失败',
  )
}

export function deactivateMessageTemplate(
  templateId: string,
  input: MessageTemplateStatusInput,
): Promise<MessageTemplateRecord> {
  return apiRequest(
    `/api/message-templates/${templateId}/deactivate`,
    {
      method: 'POST',
      body: JSON.stringify({
        expected_version: input.expectedVersion,
        idempotency_key: input.idempotencyKey ?? crypto.randomUUID(),
      }),
    },
    '停用沟通模板失败',
  )
}

export function fetchCommunicationRecords(
  filters: CommunicationRecordFilters = {},
): Promise<CommunicationRecordListRecord> {
  const query = new URLSearchParams()
  if (filters.contextType) query.set('context_type', filters.contextType)
  if (filters.contextId) query.set('context_id', filters.contextId)
  if (filters.applicationId) query.set('application_id', filters.applicationId)
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest(`/api/communications${suffix}`, {}, '无法读取沟通留痕')
}

export function fetchCommunicationRecord(recordId: string): Promise<CommunicationRecordDetailRecord> {
  return apiRequest(`/api/communications/${recordId}`, {}, '无法读取沟通留痕详情')
}

export function previewCommunication(
  input: CommunicationPreviewInput,
): Promise<CommunicationPreviewRecord> {
  return apiRequest(
    '/api/communications/preview',
    {
      method: 'POST',
      body: JSON.stringify({
        template_version_id: input.templateVersionId,
        context_type: input.contextType,
        context_id: input.contextId,
        subject_override: input.subjectOverride ?? null,
        body_override: input.bodyOverride ?? null,
      }),
    },
    '\u751f\u6210\u6c9f\u901a\u9884\u89c8\u5931\u8d25',
  )
}

export function recordCommunicationCopyAudit(
  input: CommunicationCopyAuditInput,
): Promise<CommunicationCopyAuditRecord> {
  return apiRequest(
    '/api/communications/copy-audit',
    {
      method: 'POST',
      body: JSON.stringify({
        context_type: input.contextType,
        context_id: input.contextId,
        template_version_id: input.templateVersionId ?? null,
        subject: input.subject,
        body: input.body,
        idempotency_key: input.idempotencyKey ?? crypto.randomUUID(),
      }),
    },
    '\u8bb0\u5f55\u6c9f\u901a\u7559\u75d5\u5931\u8d25',
  )
}

export function fetchOffers(status?: OfferStatus, jobId?: string): Promise<OfferSummary[]> {
  const query = new URLSearchParams()
  if (status) query.set('status', status)
  if (jobId) query.set('job_id', jobId)
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest(`/api/offers${suffix}`, {}, '无法读取 Offer 列表')
}

export function fetchOffer(offerId: string): Promise<OfferRecord> {
  return apiRequest(`/api/offers/${offerId}`, {}, '无法读取 Offer 详情')
}

export function fetchOfferPortalLinks(offerId: string): Promise<OfferPortalLinkRecord[]> {
  return apiRequest(
    `/api/offers/${offerId}/portal-links`,
    {},
    '无法读取候选人链接记录',
  )
}

export function createOfferPortalLink(
  offerId: string,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<OfferPortalLinkIssuedRecord> {
  return apiRequest(
    `/api/offers/${offerId}/portal-links`,
    {
      method: 'POST',
      body: JSON.stringify({ idempotency_key: idempotencyKey }),
    },
    '生成候选人链接失败',
  )
}

export function regenerateOfferPortalLink(
  offerId: string,
  reason: string,
  idempotencyKey: string = crypto.randomUUID(),
  revocationIdempotencyKey: string = crypto.randomUUID(),
): Promise<OfferPortalLinkIssuedRecord> {
  return apiRequest(
    `/api/offers/${offerId}/portal-links/regenerate`,
    {
      method: 'POST',
      body: JSON.stringify({
        idempotency_key: idempotencyKey,
        revocation_idempotency_key: revocationIdempotencyKey,
        reason,
      }),
    },
    '重新生成候选人链接失败',
  )
}

export function revokeOfferPortalLink(
  offerId: string,
  linkId: string,
  reason: string,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<OfferPortalLinkRecord> {
  return apiRequest(
    `/api/offers/${offerId}/portal-links/${linkId}/revoke`,
    {
      method: 'POST',
      body: JSON.stringify({ idempotency_key: idempotencyKey, reason }),
    },
    '撤回候选人链接失败',
  )
}

export function fetchOfferPortalStatus(token: string): Promise<OfferPortalStatusRecord> {
  return apiRequest(
    '/api/portal/offers/status',
    { method: 'POST', body: JSON.stringify({ token }) },
    '无法验证候选人链接',
    false,
  )
}

export function verifyOfferPortal(
  token: string,
  phoneLastFour: string,
): Promise<OfferPortalVerifiedRecord> {
  return apiRequest(
    '/api/portal/offers/verify',
    {
      method: 'POST',
      body: JSON.stringify({ token, phone_last_four: phoneLastFour }),
    },
    '验证候选人身份失败',
    false,
  )
}

export function fetchOfferPortalDetail(
  token: string,
  verificationToken: string,
): Promise<CandidateOfferViewRecord> {
  return apiRequest(
    '/api/portal/offers/detail',
    {
      method: 'POST',
      body: JSON.stringify({ token, verification_token: verificationToken }),
    },
    '无法读取 Offer',
    false,
  )
}

export function respondToOfferPortal(
  token: string,
  verificationToken: string,
  decision: CandidateOfferDecision,
  rejectionReasonCode: CandidateOfferRejectionReason | null = null,
  rejectionNote: string | null = null,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<CandidateOfferViewRecord> {
  return apiRequest(
    '/api/portal/offers/respond',
    {
      method: 'POST',
      body: JSON.stringify({
        token,
        verification_token: verificationToken,
        idempotency_key: idempotencyKey,
        decision,
        rejection_reason_code: rejectionReasonCode,
        rejection_note: rejectionNote,
      }),
    },
    decision === 'accepted' ? '接受 Offer 失败' : '拒绝 Offer 失败',
    false,
  )
}

export function fetchOnboardings(
  status?: OnboardingStatus,
  jobId?: string,
  page = 1,
  pageSize = 100,
): Promise<OnboardingListRecord> {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (status) query.set('status', status)
  if (jobId) query.set('job_id', jobId)
  return apiRequest(`/api/onboardings?${query.toString()}`, {}, '无法读取入职记录')
}

export function fetchOnboarding(onboardingId: string): Promise<OnboardingDetailRecord> {
  return apiRequest(`/api/onboardings/${onboardingId}`, {}, '无法读取入职详情')
}

export function decideOnboardingDate(
  onboardingId: string,
  version: number,
  decision: 'accept' | 'propose',
  proposedDate: string | null,
  note: string | null,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<OnboardingDetailRecord> {
  return apiRequest(
    `/api/onboardings/${onboardingId}/date-decision`,
    {
      method: 'POST',
      body: JSON.stringify({
        idempotency_key: idempotencyKey,
        version,
        decision,
        proposed_date: proposedDate,
        note,
      }),
    },
    decision === 'accept' ? '确认候选人入职日期失败' : '提出入职日期失败',
  )
}

export function markOnboardingCompleted(
  onboardingId: string,
  version: number,
  actualStartDate: string,
  note: string | null,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<OnboardingDetailRecord> {
  return apiRequest(
    `/api/onboardings/${onboardingId}/onboard`,
    {
      method: 'POST',
      body: JSON.stringify({
        idempotency_key: idempotencyKey,
        version,
        actual_start_date: actualStartDate,
        note,
      }),
    },
    '标记已入职失败',
  )
}

export function abandonOnboarding(
  onboardingId: string,
  version: number,
  source: OnboardingAbandonmentSource,
  reasonCode: OnboardingAbandonmentReason,
  note: string,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<OnboardingDetailRecord> {
  return apiRequest(
    `/api/onboardings/${onboardingId}/abandon`,
    {
      method: 'POST',
      body: JSON.stringify({
        idempotency_key: idempotencyKey,
        version,
        source,
        reason_code: reasonCode,
        note,
      }),
    },
    '标记放弃入职失败',
  )
}

export function correctOnboardingStatus(
  onboardingId: string,
  version: number,
  reason: string,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<OnboardingDetailRecord> {
  return apiRequest(
    `/api/onboardings/${onboardingId}/corrections`,
    {
      method: 'POST',
      body: JSON.stringify({ idempotency_key: idempotencyKey, version, reason }),
    },
    '更正入职状态失败',
  )
}

export function createOnboardingPortalLink(
  onboardingId: string,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<OfferPortalLinkIssuedRecord> {
  return apiRequest(
    `/api/onboardings/${onboardingId}/portal-links`,
    { method: 'POST', body: JSON.stringify({ idempotency_key: idempotencyKey }) },
    '生成入职访问链接失败',
  )
}

export function regenerateOnboardingPortalLink(
  onboardingId: string,
  reason: string,
  idempotencyKey: string = crypto.randomUUID(),
  revocationIdempotencyKey: string = crypto.randomUUID(),
): Promise<OfferPortalLinkIssuedRecord> {
  return apiRequest(
    `/api/onboardings/${onboardingId}/portal-links/regenerate`,
    {
      method: 'POST',
      body: JSON.stringify({
        idempotency_key: idempotencyKey,
        revocation_idempotency_key: revocationIdempotencyKey,
        reason,
      }),
    },
    '重新生成入职访问链接失败',
  )
}

export function confirmPortalOnboardingDate(
  token: string,
  verificationToken: string,
  version: number,
  startDate: string,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<CandidateOfferViewRecord> {
  return apiRequest(
    '/api/portal/offers/onboarding/confirm-date',
    {
      method: 'POST',
      body: JSON.stringify({
        token,
        verification_token: verificationToken,
        idempotency_key: idempotencyKey,
        version,
        start_date: startDate,
      }),
    },
    '确认入职日期失败',
    false,
  )
}

export function proposePortalOnboardingDate(
  token: string,
  verificationToken: string,
  version: number,
  startDate: string,
  note: string,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<CandidateOfferViewRecord> {
  return apiRequest(
    '/api/portal/offers/onboarding/propose-date',
    {
      method: 'POST',
      body: JSON.stringify({
        token,
        verification_token: verificationToken,
        idempotency_key: idempotencyKey,
        version,
        start_date: startDate,
        note,
      }),
    },
    '提出入职日期失败',
    false,
  )
}

export function abandonPortalOnboarding(
  token: string,
  verificationToken: string,
  version: number,
  reasonCode: OnboardingAbandonmentReason,
  note: string,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<CandidateOfferViewRecord> {
  return apiRequest(
    '/api/portal/offers/onboarding/abandon',
    {
      method: 'POST',
      body: JSON.stringify({
        token,
        verification_token: verificationToken,
        idempotency_key: idempotencyKey,
        version,
        reason_code: reasonCode,
        note,
      }),
    },
    '提交放弃入职失败',
    false,
  )
}

export function createOffer(
  jobId: string,
  applicationId: string,
  idempotencyKey: string,
  content: OfferContentInput,
): Promise<OfferRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/offer`,
    {
      method: 'POST',
      body: JSON.stringify({ idempotency_key: idempotencyKey, ...content }),
    },
    '创建 Offer 失败',
  )
}

export function createOfferVersion(
  offerId: string,
  idempotencyKey: string,
  sourceVersionId: string,
  content: OfferContentInput,
): Promise<OfferRecord> {
  return apiRequest(
    `/api/offers/${offerId}/versions`,
    {
      method: 'POST',
      body: JSON.stringify({
        idempotency_key: idempotencyKey,
        source_version_id: sourceVersionId,
        ...content,
      }),
    },
    '保存 Offer 新版本失败',
  )
}

export function submitOffer(offerId: string, versionId: string): Promise<OfferRecord> {
  return apiRequest(
    `/api/offers/${offerId}/submit`,
    {
      method: 'POST',
      body: JSON.stringify({ idempotency_key: crypto.randomUUID(), version_id: versionId }),
    },
    '提交 Offer 失败',
  )
}

export function decideOfferAsManager(
  offerId: string,
  versionId: string,
  decision: 'confirmed' | 'rejected',
  comment: string,
): Promise<OfferRecord> {
  return apiRequest(
    `/api/offers/${offerId}/manager-decision`,
    {
      method: 'POST',
      body: JSON.stringify({
        idempotency_key: crypto.randomUUID(),
        version_id: versionId,
        decision,
        comment,
      }),
    },
    decision === 'confirmed' ? '确认录用失败' : '驳回 Offer 失败',
  )
}

export function decideOfferAsApprover(
  offerId: string,
  versionId: string,
  decision: 'approved' | 'rejected',
  comment: string,
): Promise<OfferRecord> {
  return apiRequest(
    `/api/offers/${offerId}/approval-decision`,
    {
      method: 'POST',
      body: JSON.stringify({
        idempotency_key: crypto.randomUUID(),
        version_id: versionId,
        decision,
        comment,
      }),
    },
    decision === 'approved' ? '批准 Offer 失败' : '驳回 Offer 失败',
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

export function fetchTalentPoolGroups(filters: {
  status?: TalentPoolGroupStatus
  query?: string
  limit?: number
  offset?: number
} = {}): Promise<TalentPoolGroupListRecord> {
  const query = new URLSearchParams()
  if (filters.status) query.set('status', filters.status)
  if (filters.query?.trim()) query.set('query', filters.query.trim())
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest(`/api/talent-pool/groups${suffix}`, {}, '无法读取人才分组')
}

export function createTalentPoolGroup(
  name: string,
  description: string | null,
): Promise<TalentPoolGroupRecord> {
  return apiRequest(
    '/api/talent-pool/groups',
    {
      method: 'POST',
      body: JSON.stringify({ name, description, idempotency_key: crypto.randomUUID() }),
    },
    '创建人才分组失败',
  )
}

export function updateTalentPoolGroup(
  groupId: string,
  expectedVersion: number,
  values: { name?: string; description?: string | null },
): Promise<TalentPoolGroupRecord> {
  return apiRequest(
    `/api/talent-pool/groups/${encodeURIComponent(groupId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify({
        ...values,
        expected_version: expectedVersion,
        idempotency_key: crypto.randomUUID(),
      }),
    },
    '更新人才分组失败',
  )
}

export function archiveTalentPoolGroup(
  groupId: string,
  expectedVersion: number,
  reason: string,
): Promise<TalentPoolGroupRecord> {
  return apiRequest(
    `/api/talent-pool/groups/${encodeURIComponent(groupId)}/archive`,
    {
      method: 'POST',
      body: JSON.stringify({
        expected_version: expectedVersion,
        reason,
        idempotency_key: crypto.randomUUID(),
      }),
    },
    '归档人才分组失败',
  )
}

export function fetchTalentPoolMemberships(filters: {
  status?: TalentPoolMembershipStatus
  groupStatus?: TalentPoolGroupStatus
  groupId?: string
  query?: string
  limit?: number
  offset?: number
} = {}): Promise<TalentPoolMembershipListRecord> {
  const query = new URLSearchParams()
  if (filters.status) query.set('status', filters.status)
  if (filters.groupStatus) query.set('group_status', filters.groupStatus)
  if (filters.groupId) query.set('group_id', filters.groupId)
  if (filters.query?.trim()) query.set('query', filters.query.trim())
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest(`/api/talent-pool/memberships${suffix}`, {}, '无法读取人才成员')
}

export function addTalentPoolMemberships(
  groupId: string,
  expectedGroupVersion: number,
  candidateIds: string[],
  reason: string,
): Promise<TalentPoolMembershipOperationRecord> {
  return apiRequest(
    `/api/talent-pool/groups/${encodeURIComponent(groupId)}/memberships`,
    {
      method: 'POST',
      body: JSON.stringify({
        members: candidateIds.map((candidateId) => ({ candidate_id: candidateId })),
        reason,
        expected_group_version: expectedGroupVersion,
        idempotency_key: crypto.randomUUID(),
      }),
    },
    '加入人才库失败',
  )
}

export function removeTalentPoolMemberships(
  groupId: string,
  expectedGroupVersion: number,
  candidateIds: string[],
  reason: string,
): Promise<TalentPoolMembershipOperationRecord> {
  return apiRequest(
    `/api/talent-pool/groups/${encodeURIComponent(groupId)}/memberships/remove`,
    {
      method: 'POST',
      body: JSON.stringify({
        candidate_ids: candidateIds,
        reason,
        expected_group_version: expectedGroupVersion,
        idempotency_key: crypto.randomUUID(),
      }),
    },
    '移出人才库失败',
  )
}

export function fetchTalentRecommendations(
  jobId: string,
  filters: TalentRecommendationFilters = {},
): Promise<TalentRecommendationRunListRecord> {
  const query = new URLSearchParams()
  if (filters.status) query.set('status', filters.status)
  if (filters.createdById) query.set('created_by_id', filters.createdById)
  if (filters.createdFrom) query.set('created_from', filters.createdFrom)
  if (filters.createdTo) query.set('created_to', filters.createdTo)
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest(
    `/api/jobs/${encodeURIComponent(jobId)}/recommendations${suffix}`,
    {},
    '无法读取人才推荐任务',
  )
}

export function fetchTalentRecommendation(
  jobId: string,
  runId: string,
): Promise<TalentRecommendationRunDetailRecord> {
  return apiRequest(
    `/api/jobs/${encodeURIComponent(jobId)}/recommendations/${encodeURIComponent(runId)}`,
    {},
    '无法读取人才推荐详情',
  )
}

export function createTalentRecommendation(
  jobId: string,
  groupIds: string[],
  aiInputMode: 'raw' | 'redacted',
  idempotencyKey: string = crypto.randomUUID(),
): Promise<TalentRecommendationCreateRecord> {
  return apiRequest(
    `/api/jobs/${encodeURIComponent(jobId)}/recommendations`,
    {
      method: 'POST',
      body: JSON.stringify({
        group_ids: groupIds,
        ai_input_mode: aiInputMode,
        idempotency_key: idempotencyKey,
      }),
    },
    '创建人才推荐任务失败',
  )
}

function talentRecommendationAction(
  jobId: string,
  runId: string,
  action: 'cancel' | 'retry-failures',
  expectedVersion: number,
  idempotencyKey: string,
): Promise<TalentRecommendationRunRecord> {
  return apiRequest(
    `/api/jobs/${encodeURIComponent(jobId)}/recommendations/${encodeURIComponent(runId)}/${action}`,
    {
      method: 'POST',
      body: JSON.stringify({
        expected_version: expectedVersion,
        idempotency_key: idempotencyKey,
      }),
    },
    action === 'cancel' ? '取消人才推荐任务失败' : '重试人才推荐任务失败',
  )
}

export function cancelTalentRecommendation(
  jobId: string,
  runId: string,
  expectedVersion: number,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<TalentRecommendationRunRecord> {
  return talentRecommendationAction(
    jobId,
    runId,
    'cancel',
    expectedVersion,
    idempotencyKey,
  )
}

export function retryTalentRecommendationFailures(
  jobId: string,
  runId: string,
  expectedVersion: number,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<TalentRecommendationRunRecord> {
  return talentRecommendationAction(
    jobId,
    runId,
    'retry-failures',
    expectedVersion,
    idempotencyKey,
  )
}

export function selectTalentRecommendationCandidates(
  jobId: string,
  runId: string,
  resultIds: string[],
  confirmedStaleResultIds: string[] = [],
  idempotencyKey: string = crypto.randomUUID(),
): Promise<TalentRecommendationSelectionRecord> {
  return apiRequest(
    `/api/jobs/${encodeURIComponent(jobId)}/recommendations/${encodeURIComponent(runId)}/select`,
    {
      method: 'POST',
      body: JSON.stringify({
        result_ids: resultIds,
        confirmed_stale_result_ids: confirmedStaleResultIds,
        idempotency_key: idempotencyKey,
      }),
    },
    '推荐候选人转应聘失败',
  )
}

export function updateCandidatePhone(
  candidateId: string,
  phone: string,
  reason: string,
): Promise<CandidatePhoneUpdateRecord> {
  return apiRequest(
    `/api/candidates/${encodeURIComponent(candidateId)}/phone`,
    {
      method: 'PATCH',
      body: JSON.stringify({ phone, reason }),
    },
    '修正候选人手机号失败',
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
  applicationId: string,
  expectedStage: CandidateStage,
  targetStage: CandidateStage,
  reason?: string,
): Promise<CandidateStageUpdateRecord> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/stage`,
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
  applicationId: string,
): Promise<CandidateProcessTimelineEventRecord[]> {
  return apiRequest(
    `/api/jobs/${jobId}/applications/${applicationId}/timeline`,
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
