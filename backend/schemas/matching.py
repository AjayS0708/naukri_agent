from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Aggressiveness(StrEnum):
    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    AGGRESSIVE = "AGGRESSIVE"


class MatchDecisionEnum(StrEnum):
    APPLY = "APPLY"
    SKIP = "SKIP"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


class SkipReason(StrEnum):
    LOCATION_NOT_ALLOWED = "LOCATION_NOT_ALLOWED"
    EXPERIENCE_TOO_HIGH = "EXPERIENCE_TOO_HIGH"
    SALARY_BELOW_MINIMUM = "SALARY_BELOW_MINIMUM"
    EMPLOYMENT_TYPE_NOT_ALLOWED = "EMPLOYMENT_TYPE_NOT_ALLOWED"
    DUPLICATE_JOB = "DUPLICATE_JOB"
    OUTSIDE_SEARCH_SCOPE = "OUTSIDE_SEARCH_SCOPE"
    SUSPICIOUS_JOB = "SUSPICIOUS_JOB"
    COMPANY_UNIDENTIFIED = "COMPANY_UNIDENTIFIED"
    INSUFFICIENT_RELEVANCE = "INSUFFICIENT_RELEVANCE"
    APPLICATION_LIMIT_REACHED = "APPLICATION_LIMIT_REACHED"
    PROFILE_NOT_CONFIRMED = "PROFILE_NOT_CONFIRMED"
    MISSING_REQUIRED_DATA = "MISSING_REQUIRED_DATA"
    UNKNOWN = "UNKNOWN"


class JobPreferenceBase(BaseModel):
    locations: list[str] = Field(default_factory=list)
    job_titles: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)
    min_salary_lpa: float | None = None
    aggressiveness: Aggressiveness = Field(default=Aggressiveness.BALANCED)
    max_daily_applications: int = Field(default=20, ge=1)
    max_hourly_applications: int = Field(default=4, ge=1)


class JobPreferenceResponse(JobPreferenceBase):
    id: int
    created_at: datetime
    updated_at: datetime


class JobPreferenceUpdate(JobPreferenceBase):
    model_config = ConfigDict(extra="forbid")
    pass


class MatchDecision(BaseModel):
    decision: MatchDecisionEnum
    reason: str
    skip_reason: SkipReason | None = None
    matched_rules: list[str] = Field(default_factory=list)
    failed_rules: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    match_score: int | None = None
    requires_attention: bool = False

class EvaluateJobRequest(BaseModel):
    title: str
    company: str
    description: str | None = None
    url: str | None = None
