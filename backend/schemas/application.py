from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ApplicationStatus(StrEnum):
    PRE_APPLY = "PRE_APPLY"
    DISCOVERED = "DISCOVERED"
    FILTERED = "FILTERED"
    AI_ANALYZED = "AI_ANALYZED"
    APPROVED_BY_RULES = "APPROVED_BY_RULES"
    APPLICATION_STARTED = "APPLICATION_STARTED"
    APPLIED = "APPLIED"
    SUBMITTED = "SUBMITTED"
    EXTERNAL_APPLICATION = "EXTERNAL_APPLICATION"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    SKIPPED = "SKIPPED"


class ApplicationStartResult(StrEnum):
    PRE_APPLY = "PRE_APPLY"
    FORM_OPENED = "FORM_OPENED"
    APPLIED = "APPLIED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


class ApplicationMethod(StrEnum):
    NAUKRI_NATIVE = "NAUKRI_NATIVE"
    EXTERNAL = "EXTERNAL"


class ApplicationAnswerType(StrEnum):
    FACTUAL = "FACTUAL"
    GENERATED = "GENERATED"
    FALLBACK = "FALLBACK"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


class ApplicationAnswerSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    application_id: int
    question: str
    answer: str
    answer_type: ApplicationAnswerType | None = None
    confidence: int | None = Field(None, ge=0, le=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApplicationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    job_id: int
    status: ApplicationStatus
    application_method: ApplicationMethod | None = None
    started_at: datetime | None = None
    applied_at: datetime | None = None
    failure_reason: str | None = None
    skip_reason: str | None = None
    confirmation_evidence: str | None = None
    external_url: str | None = None
    needs_attention: bool = False
    is_dry_run: bool = False
    # E5-R16: row was repaired from a read-only Naukri history review.
    reconciled_from_history: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: int
    status: ApplicationStatus = ApplicationStatus.APPLICATION_STARTED
    application_method: ApplicationMethod | None = None
    is_dry_run: bool = False


class ApplicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ApplicationStatus | None = None
    application_method: ApplicationMethod | None = None
    started_at: datetime | None = None
    applied_at: datetime | None = None
    failure_reason: str | None = None
    skip_reason: str | None = None
    confirmation_evidence: str | None = None
    external_url: str | None = None
    needs_attention: bool | None = None
    is_dry_run: bool | None = None


class ApplicationStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: int


class ApplicationStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_id: int
    status: ApplicationStatus
    message: str


class ApplicationHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    applications: list[ApplicationSchema]
    total: int


class ReconcileStaleExternalsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Rule 1 (E5-R5.3): exact page-chrome signature matches.
    affected_count: int
    application_ids: list[int]
    job_ids: list[int]
    signature: str
    # Rule 2 (E5-R6): pre-R5.4 native-URL misclassification recovery.
    recovered_count: int = 0
    recovered_application_ids: list[int] = Field(default_factory=list)
    recovered_job_ids: list[int] = Field(default_factory=list)
    # EXTERNAL_APPLICATION rows intentionally left unchanged (ambiguous or genuine).
    remaining_external_ids: list[int] = Field(default_factory=list)


class ReconcileHistoryResponse(BaseModel):
    """Report of a read-only Naukri application-history reconciliation (E5-R16)."""
    model_config = ConfigDict(extra="forbid")

    # LOGIN_REQUIRED when the session is not authenticated; no data was read.
    status: str
    message: str = ""
    history_entries: int = 0
    confirmed_local_job_ids: list[int] = Field(default_factory=list)
    reconciled_count: int = 0
    reconciled_application_ids: list[int] = Field(default_factory=list)
    reconciled_job_ids: list[int] = Field(default_factory=list)
    local_applied_without_history_evidence: list[int] = Field(default_factory=list)
    ambiguous: list[str] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list)
    protected_job_ids: list[int] = Field(default_factory=list)
