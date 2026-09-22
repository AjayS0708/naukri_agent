from enum import StrEnum
from datetime import UTC, datetime
from typing import Optional

from pydantic import BaseModel, Field


class FeedbackType(StrEnum):
    """Types of user feedback."""
    RELEVANT = "RELEVANT"
    NOT_RELEVANT = "NOT_RELEVANT"
    APPLIED = "APPLIED"
    SKIPPED = "SKIPPED"
    INCORRECT_MATCH = "INCORRECT_MATCH"
    GOOD_MATCH = "GOOD_MATCH"
    TOO_SENIOR = "TOO_SENIOR"
    TOO_JUNIOR = "TOO_JUNIOR"
    WRONG_LOCATION = "WRONG_LOCATION"
    SALARY_TOO_LOW = "SALARY_TOO_LOW"


class FeedbackCreate(BaseModel):
    """Request to submit feedback."""
    job_id: int
    feedback_type: FeedbackType
    comments: Optional[str] = Field(default=None, max_length=500)


class FeedbackResponse(BaseModel):
    """Feedback response."""
    id: int
    job_id: int
    feedback_type: FeedbackType
    comments: Optional[str]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FeedbackSummary(BaseModel):
    """Summary of feedback for analytics."""
    total_feedback: int
    relevant_count: int
    not_relevant_count: int
    applied_count: int
    skipped_count: int
    incorrect_match_count: int
    good_match_count: int
    relevance_rate: float = Field(description="Rate of relevant feedback (0-1)")
