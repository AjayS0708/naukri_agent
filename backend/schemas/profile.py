from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ProfileStatus(StrEnum):
    EMPTY = "EMPTY"
    RESUME_UPLOADED = "RESUME_UPLOADED"
    EXTRACTING = "EXTRACTING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CONFIRMED = "CONFIRMED"
    ERROR = "ERROR"


class Education(BaseModel):
    model_config = ConfigDict(extra="forbid")
    degree: str | None = None
    field: str | None = None
    institution: str | None = None
    graduation_year: int | None = Field(default=None, ge=1900, le=2100)


class Experience(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    company: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)


class ProfileData(BaseModel):
    """Facts only. Null and empty collections intentionally represent unknown data."""
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    education: list[Education] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    programming_languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    current_role: str | None = None
    location: str | None = None
    current_ctc: str | None = None
    notice_period: str | None = None


class ResumeUploadResponse(BaseModel):
    profile_id: int
    status: ProfileStatus
    resume_hash: str
    duplicate: bool


class ProfileResponse(BaseModel):
    id: int | None = None
    status: ProfileStatus
    confirmed: bool
    data: ProfileData | None = None
    resume_hash: str | None = None
    original_filename: str | None = None
    uploaded_at: datetime | None = None
    updated_at: datetime | None = None


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: ProfileData
