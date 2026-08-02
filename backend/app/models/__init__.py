from app.models.audit import AuditLog
from app.models.candidate import (
    ApplicationResumeDocument,
    Candidate,
    CandidateDuplicateReview,
    JobApplication,
)
from app.models.candidate_process import CandidateProcess, CandidateProcessEvent
from app.models.interview import (
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    InterviewDimensionRating,
    InterviewEvaluation,
    InterviewPlanVersion,
    InterviewQuestion,
    InterviewQuestionResponse,
    InterviewRound,
    InterviewScoreAnchor,
    InterviewScoreDimension,
)
from app.models.interview_report import InterviewReport, InterviewReportVersion
from app.models.job import HardRequirement, Job, JobCriteriaVersion, ScoringDimension
from app.models.knowledge import ResumeEmbeddingChunk
from app.models.message import CommunicationRecord, MessageTemplate, MessageTemplateVersion
from app.models.notification import InternalNotification
from app.models.offer import (
    Offer,
    OfferApproval,
    OfferManagerConfirmation,
    OfferPortalLink,
    OfferResponse,
    OfferVersion,
)
from app.models.onboarding import Onboarding, OnboardingEvent
from app.models.recruitment_request import (
    RecruitmentRequest,
    RecruitmentRequestApproval,
    RecruitmentRequestVersion,
)
from app.models.resume import (
    CandidateProfile,
    DimensionScore,
    EvidenceCitation,
    RecruiterDecision,
    ResumeDocument,
    ResumeRedaction,
    ResumeTextSegment,
    ScreeningBatch,
    ScreeningResult,
)
from app.models.talent_pool import (
    TalentPoolGroup,
    TalentPoolMembership,
    TalentPoolMembershipEvent,
)
from app.models.talent_recommendation import (
    TalentRecommendationResult,
    TalentRecommendationRun,
    TalentRecommendationRunCandidate,
    TalentRecommendationRunEvent,
    TalentRecommendationRunGroup,
)
from app.models.user import Role, User, UserRole

__all__ = [
    "AuditLog",
    "ApplicationResumeDocument",
    "Candidate",
    "CandidateDuplicateReview",
    "CandidateProfile",
    "CandidateInterviewRound",
    "CandidateInterviewSchedule",
    "CandidateProcess",
    "CandidateProcessEvent",
    "CommunicationRecord",
    "DimensionScore",
    "EvidenceCitation",
    "HardRequirement",
    "InterviewDimensionRating",
    "InterviewEvaluation",
    "InterviewPlanVersion",
    "InterviewQuestion",
    "InterviewQuestionResponse",
    "InterviewReport",
    "InterviewReportVersion",
    "InterviewRound",
    "InterviewScoreAnchor",
    "InterviewScoreDimension",
    "InternalNotification",
    "Job",
    "JobApplication",
    "JobCriteriaVersion",
    "MessageTemplate",
    "MessageTemplateVersion",
    "Offer",
    "OfferApproval",
    "OfferManagerConfirmation",
    "OfferPortalLink",
    "OfferResponse",
    "OfferVersion",
    "Onboarding",
    "OnboardingEvent",
    "RecruiterDecision",
    "RecruitmentRequest",
    "RecruitmentRequestApproval",
    "RecruitmentRequestVersion",
    "ResumeDocument",
    "ResumeEmbeddingChunk",
    "ResumeRedaction",
    "ResumeTextSegment",
    "Role",
    "ScoringDimension",
    "ScreeningBatch",
    "ScreeningResult",
    "TalentPoolGroup",
    "TalentPoolMembership",
    "TalentPoolMembershipEvent",
    "TalentRecommendationResult",
    "TalentRecommendationRun",
    "TalentRecommendationRunCandidate",
    "TalentRecommendationRunEvent",
    "TalentRecommendationRunGroup",
    "User",
    "UserRole",
]
