from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.core.config import get_settings
from backend.core.exceptions import ValidationError
from backend.core.exceptions import ProfileExtractionError
from backend.database.database import Base
from backend.schemas.profile import ProfileData, ProfileStatus, ProfileUpdateRequest
from backend.services.profile.profile_service import ProfileService


class FakeExtractor:
    def extract(self, _: str) -> ProfileData:
        return ProfileData(name="Asha Rao", skills=["Python", "SQL"], current_role="Analyst")


class FailingExtractor:
    def extract(self, _: str) -> ProfileData:
        raise ProfileExtractionError("Invalid AI output")


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


def test_profile_schema_rejects_unknown_fields() -> None:
    with pytest.raises(Exception):
        ProfileData.model_validate({"skills": ["Python"], "invented_skill": "AWS"})


def test_extraction_failure_preserves_resume_as_error(profile_session: Session, resume_bytes: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "resume_storage_dir", tmp_path)
    with pytest.raises(ProfileExtractionError):
        ProfileService(profile_session, extractor=FailingExtractor()).upload_resume("candidate.pdf", "application/pdf", resume_bytes)
    assert ProfileService(profile_session, extractor=FakeExtractor()).get_current_profile().status is ProfileStatus.ERROR
