from pathlib import Path

import pymupdf
import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.core.config import get_settings
from backend.core.exceptions import ProfileExtractionError
from backend.core.exceptions import ValidationError
from backend.database.database import Base
from backend.schemas.profile import ProfileData, ProfileStatus, ProfileUpdateRequest
from backend.services.profile.profile_extractor import prepare_resume_text_for_ai
from backend.services.profile.profile_service import ProfileService


class FakeExtractor:
    def extract(self, _: str) -> ProfileData:
        return ProfileData(name="Asha Rao", skills=["Python", "SQL"], current_role="Analyst")


class FailingExtractor:
    def extract(self, _: str) -> ProfileData:
        raise ProfileExtractionError("Invalid AI output")


class RetryExtractor:
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, _: str) -> ProfileData:
        self.calls += 1
        if self.calls == 1:
            raise ProfileExtractionError("Temporary failure")
        return ProfileData(name="Asha Rao", skills=["Python"])


@pytest.fixture
def profile_session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def resume_bytes() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Asha Rao\nData Analyst\nPython SQL Power BI Excel\nBuilt reporting dashboards and data models for business teams.")
    content = document.tobytes()
    document.close()
    return content


@pytest.fixture
def multi_page_resume_bytes() -> bytes:
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text((72, 72), "Asha Rao Data Analyst Python SQL")
    second = document.new_page()
    second.insert_text((72, 72), "Power BI Excel and dashboard ownership with cross-team collaboration")
    content = document.tobytes()
    document.close()
    return content


def test_upload_extract_edit_and_confirm(profile_session: Session, resume_bytes: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "resume_storage_dir", tmp_path)
    service = ProfileService(profile_session, extractor=FakeExtractor())

    uploaded = service.upload_resume("candidate.pdf", "application/pdf", resume_bytes)
    reviewed = service.get_current_profile()
    updated = service.update_current_profile(ProfileUpdateRequest(data=reviewed.data.model_copy(update={"location": "Bengaluru"})))
    confirmed = service.confirm_current_profile()

    assert uploaded.status is ProfileStatus.REVIEW_REQUIRED
    assert reviewed.confirmed is False
    assert updated.data.location == "Bengaluru"
    assert confirmed.status is ProfileStatus.CONFIRMED
    assert confirmed.confirmed is True
    assert confirmed.file_size == len(resume_bytes)
    assert (tmp_path / f"{uploaded.resume_hash}.pdf").is_file()


def test_identical_resume_reuses_existing_profile(profile_session: Session, resume_bytes: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "resume_storage_dir", tmp_path)
    service = ProfileService(profile_session, extractor=FakeExtractor())
    first = service.upload_resume("candidate.pdf", "application/pdf", resume_bytes)
    second = service.upload_resume("renamed.pdf", "application/pdf", resume_bytes)

    assert first.profile_id == second.profile_id
    assert second.duplicate is True


@pytest.mark.parametrize("filename,content_type,content", [("candidate.txt", "text/plain", b"%PDF-1.7"), ("candidate.pdf", "application/pdf", b"not a pdf")])
def test_upload_rejects_invalid_file(profile_session: Session, filename: str, content_type: str, content: bytes) -> None:
    with pytest.raises(ValidationError):
        ProfileService(profile_session, extractor=FakeExtractor()).upload_resume(filename, content_type, content)


def test_upload_rejects_oversized_file(profile_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_resume_file_size_bytes", 6)
    with pytest.raises(ValidationError):
        ProfileService(profile_session, extractor=FakeExtractor()).upload_resume("candidate.pdf", "application/pdf", b"%PDF-1.7")


def test_pdf_extraction_uses_multi_page_content(profile_session: Session, multi_page_resume_bytes: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "resume_storage_dir", tmp_path)
    service = ProfileService(profile_session, extractor=FakeExtractor())
    uploaded = service.upload_resume("candidate.pdf", "application/pdf", multi_page_resume_bytes)
    profile = service.get_current_profile()
    assert uploaded.status is ProfileStatus.REVIEW_REQUIRED
    assert profile.status is ProfileStatus.REVIEW_REQUIRED


def test_resume_original_filename_is_sanitized(profile_session: Session, resume_bytes: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "resume_storage_dir", tmp_path)
    service = ProfileService(profile_session, extractor=FakeExtractor())
    service.upload_resume("..\\..\\secret\\resume.pdf", "application/pdf", resume_bytes)
    profile = service.get_current_profile()
    assert profile.original_filename == "resume.pdf"


def test_profile_schema_rejects_unknown_fields() -> None:
    with pytest.raises(PydanticValidationError):
        ProfileData.model_validate({"skills": ["Python"], "invented_skill": "AWS"})


def test_profile_extraction_retries_once(profile_session: Session, resume_bytes: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "resume_storage_dir", tmp_path)
    monkeypatch.setattr(get_settings(), "profile_extraction_retries", 1)
    extractor = RetryExtractor()
    service = ProfileService(profile_session, extractor=extractor)
    uploaded = service.upload_resume("candidate.pdf", "application/pdf", resume_bytes)
    assert uploaded.status is ProfileStatus.REVIEW_REQUIRED
    assert extractor.calls == 2


def test_extraction_failure_preserves_resume_as_error(profile_session: Session, resume_bytes: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "resume_storage_dir", tmp_path)
    with pytest.raises(ProfileExtractionError):
        ProfileService(profile_session, extractor=FailingExtractor()).upload_resume("candidate.pdf", "application/pdf", resume_bytes)
    assert ProfileService(profile_session, extractor=FakeExtractor()).get_current_profile().status is ProfileStatus.ERROR


def test_confirm_requires_review_status(profile_session: Session, resume_bytes: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "resume_storage_dir", tmp_path)
    service = ProfileService(profile_session, extractor=FakeExtractor())
    service.upload_resume("candidate.pdf", "application/pdf", resume_bytes)
    service.confirm_current_profile()
    with pytest.raises(ValidationError):
        service.confirm_current_profile()


def test_prepare_resume_text_for_ai_truncates_large_payload() -> None:
    long_text = ("Python SQL PowerBI " * 2000).strip()
    prepared = prepare_resume_text_for_ai(long_text, 1000)
    assert len(prepared) <= 1000
    assert "[TRUNCATED]" in prepared
