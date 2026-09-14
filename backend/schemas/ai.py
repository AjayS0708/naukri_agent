from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.profile import ProfileData


class AIProviderStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    AUTH_ERROR = "AUTH_ERROR"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class AIOperation(StrEnum):
    PROFILE_EXTRACTION = "PROFILE_EXTRACTION"
    JOB_ANALYSIS = "JOB_ANALYSIS"
    APPLICATION_ANSWER = "APPLICATION_ANSWER"
    DUPLICATE_ANALYSIS = "DUPLICATE_ANALYSIS"
    JOB_QUALITY_ANALYSIS = "JOB_QUALITY_ANALYSIS"
    FEEDBACK_ANALYSIS = "FEEDBACK_ANALYSIS"


class AIRecommendation(StrEnum):
    APPLY = "APPLY"
    SKIP = "SKIP"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


class JobQuality(StrEnum):
    GOOD = "GOOD"
    AVERAGE = "AVERAGE"
    LOW = "LOW"
    SUSPICIOUS = "SUSPICIOUS"


class ApplicationAnswerType(StrEnum):
    FACTUAL = "FACTUAL"
    GENERATED = "GENERATED"
    FALLBACK = "FALLBACK"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


class JobAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_score: int = Field(ge=0, le=100)
    role_match: bool
    skill_match: bool
    experience_match: bool
    location_match: bool
    salary_match: bool
    job_quality: JobQuality
    duplicate_probability: float = Field(ge=0, le=1)
    suspicious: bool
    recommendation: AIRecommendation
    short_reason: str = Field(min_length=4, max_length=280)


class ApplicationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=2, max_length=400)
    answer: str = Field(min_length=0, max_length=1200)
    answer_type: ApplicationAnswerType
    confidence: float = Field(ge=0, le=1)
    needs_attention: bool = False


class AIStatusResponse(BaseModel):
    provider: str
    status: AIProviderStatus
    model: str | None = None
    requests: int = 0
    cached: int = 0
    errors: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProfileExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resume_text: str = Field(min_length=20)
    resume_hash: str | None = None


class ProfileExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_version: str
    profile: ProfileData
