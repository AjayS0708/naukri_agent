"""E5-R21 schemas: pending screening questions and screening-answer memory."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PendingQuestionResponse(BaseModel):
    """The screening question an active run is waiting on (if any)."""
    model_config = ConfigDict(extra="forbid")

    found: bool = False
    pending_question_id: Optional[int] = None
    run_token: Optional[str] = None
    question_text: Optional[str] = None
    question_type: Optional[str] = None
    options: Optional[list[str]] = None
    employer: Optional[str] = None
    job_title: Optional[str] = None
    job_id: Optional[int] = None
    application_id: Optional[int] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None


class AnswerQuestionRequest(BaseModel):
    """Answer (or skip) the pending screening question of the active run."""
    model_config = ConfigDict(extra="forbid")

    pending_question_id: int
    run_token: Optional[str] = Field(
        default=None,
        description="Must match the active run when provided.",
    )
    answer: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="The answer text (or the chosen option verbatim).",
    )
    skip: bool = Field(
        default=False,
        description="Skip this job instead of answering the question.",
    )
    scope: str = Field(
        default="JOB",
        description="Reuse scope for the saved answer: JOB, EMPLOYER or GLOBAL.",
    )
    remember: bool = Field(
        default=True,
        description="Persist the answer for later applications (scope applies).",
    )
    allow_global_reuse: bool = Field(
        default=False,
        description=(
            "Explicit authorisation required to store a context-sensitive "
            "answer (salary, notice, relocation, ...) with GLOBAL scope."
        ),
    )


class AnswerQuestionResponse(BaseModel):
    """Result of answering/skipping the pending question."""
    model_config = ConfigDict(extra="forbid")

    status: str  # ANSWERED | SKIPPED
    pending_question_id: int
    saved_to_memory: bool = False
    answer_scope: Optional[str] = None
    message: str


class ScreeningAnswerResponse(BaseModel):
    """A stored reusable screening answer."""
    model_config = ConfigDict(extra="forbid")

    id: int
    question_text: str
    answer: str
    answer_type: str
    scope: str
    employer: Optional[str] = None
    job_id: Optional[int] = None
    source: str
    verification_status: str
    context_sensitive: bool = False
    reuse_count: int = 0
    last_used_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ScreeningAnswerUpdateRequest(BaseModel):
    """Edit an existing saved answer (its scope may be widened explicitly)."""
    model_config = ConfigDict(extra="forbid")

    answer: Optional[str] = Field(default=None, max_length=2000)
    scope: Optional[str] = None
    allow_global_reuse: bool = False
