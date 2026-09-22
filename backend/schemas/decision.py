from enum import StrEnum
from typing import Optional
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class DecisionPriority(StrEnum):
    """Priority levels for job evaluation and application ordering."""
    HARD_REJECT = "HARD_REJECT"
    SKIP = "SKIP"
    LOW_PRIORITY = "LOW_PRIORITY"
    NORMAL_PRIORITY = "NORMAL_PRIORITY"
    HIGH_PRIORITY = "HIGH_PRIORITY"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


class DecisionReasonCode(StrEnum):
    """Structured reason codes for explainable decisions."""
    # Hard filter failures
    LOCATION_MISMATCH = "LOCATION_MISMATCH"
    EXPERIENCE_TOO_HIGH = "EXPERIENCE_TOO_HIGH"
    SALARY_BELOW_MINIMUM = "SALARY_BELOW_MINIMUM"
    EMPLOYMENT_TYPE_NOT_ALLOWED = "EMPLOYMENT_TYPE_NOT_ALLOWED"
    DUPLICATE_JOB = "DUPLICATE_JOB"
    OUTSIDE_SEARCH_SCOPE = "OUTSIDE_SEARCH_SCOPE"
    PROFILE_NOT_CONFIRMED = "PROFILE_NOT_CONFIRMED"
    MISSING_REQUIRED_DATA = "MISSING_REQUIRED_DATA"
    
    # Quality and relevance
    SUSPICIOUS_JOB = "SUSPICIOUS_JOB"
    COMPANY_UNIDENTIFIED = "COMPANY_UNIDENTIFIED"
    LOW_QUALITY_POSTING = "LOW_QUALITY_POSTING"
    INCOMPLETE_DESCRIPTION = "INCOMPLETE_DESCRIPTION"
    
    # Relevance and matching
    WEAK_ROLE_MATCH = "WEAK_ROLE_MATCH"
    WEAK_SKILL_MATCH = "WEAK_SKILL_MATCH"
    INSUFFICIENT_RELEVANCE = "INSUFFICIENT_RELEVANCE"
    
    # Priority factors
    STRONG_MATCH = "STRONG_MATCH"
    GOOD_MATCH = "GOOD_MATCH"
    FRESH_JOB = "FRESH_JOB"
    HIGH_SALARY = "HIGH_SALARY"
    PREFERRED_LOCATION = "PREFERRED_LOCATION"
    PREVIOUS_POSITIVE_FEEDBACK = "PREVIOUS_POSITIVE_FEEDBACK"
    
    # System limits
    APPLICATION_LIMIT_REACHED = "APPLICATION_LIMIT_REACHED"
    AI_QUOTA_EXHAUSTED = "AI_QUOTA_EXHAUSTED"
    
    # Unknown/attention needed
    UNKNOWN = "UNKNOWN"
    REQUIRES_MANUAL_REVIEW = "REQUIRES_MANUAL_REVIEW"


class DecisionSignal(BaseModel):
    """Individual signal contributing to a decision."""
    signal_type: str = Field(description="Type of signal (e.g., 'location_match', 'skill_match')")
    value: float = Field(description="Signal value (0-1 for scores, boolean as 0/1)")
    weight: float = Field(default=1.0, description="Signal weight in final decision")
    reason: Optional[str] = Field(default=None, description="Human-readable explanation")


class DecisionQuality(BaseModel):
    """Comprehensive decision quality assessment."""
    priority: DecisionPriority
    decision_score: float = Field(ge=0, le=100, description="Overall decision score (0-100)")
    
    # Individual signal scores
    role_relevance_score: float = Field(ge=0, le=1, description="Role relevance (0-1)")
    skill_relevance_score: float = Field(ge=0, le=1, description="Skill relevance (0-1)")
    experience_compatibility_score: float = Field(ge=0, le=1, description="Experience compatibility (0-1)")
    location_match_score: float = Field(ge=0, le=1, description="Location match (0-1)")
    salary_suitability_score: float = Field(ge=0, le=1, description="Salary suitability (0-1)")
    job_quality_score: float = Field(ge=0, le=1, description="Job quality (0-1)")
    freshness_score: float = Field(ge=0, le=1, description="Job freshness (0-1)")
    
    # Risk factors
    duplicate_probability: float = Field(ge=0, le=1, description="Duplicate probability (0-1)")
    suspicious_probability: float = Field(ge=0, le=1, description="Suspicious probability (0-1)")
    
    # Historical feedback influence
    feedback_adjustment: float = Field(default=0.0, ge=-1, le=1, description="Feedback adjustment (-1 to 1)")
    
    # Decision breakdown
    primary_reason_code: DecisionReasonCode
    reason_codes: list[DecisionReasonCode] = Field(default_factory=list)
    explanation: str = Field(description="Concise human-readable explanation")
    
    # Signals breakdown
    signals: list[DecisionSignal] = Field(default_factory=list)
    
    # Metadata
    hard_filter_failed: bool = Field(default=False, description="Whether a hard filter failed")
    requires_ai_analysis: bool = Field(default=False, description="Whether AI analysis is required")
    ai_available: bool = Field(default=True, description="Whether AI analysis is available")
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JobPriorityRequest(BaseModel):
    """Request to prioritize a list of jobs."""
    job_ids: list[int] = Field(description="List of job IDs to prioritize")


class JobPriorityResponse(BaseModel):
    """Response with prioritized jobs."""
    job_id: int
    priority: DecisionPriority
    decision_score: float
    explanation: str
    primary_reason_code: DecisionReasonCode


class BulkPriorityResponse(BaseModel):
    """Response for bulk job prioritization."""
    prioritized_jobs: list[JobPriorityResponse]
    total_jobs: int
    high_priority_count: int
    normal_priority_count: int
    low_priority_count: int
    skip_count: int
    hard_reject_count: int
    needs_attention_count: int


class DecisionHistoryRequest(BaseModel):
    """Request for decision history."""
    job_id: int
    limit: int = Field(default=10, ge=1, le=100)


class DecisionHistoryResponse(BaseModel):
    """Response with decision history for a job."""
    job_id: int
    decisions: list[DecisionQuality]
