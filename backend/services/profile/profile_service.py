import hashlib
import os
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.exceptions import ProfileExtractionError, ValidationError
from backend.models.profile import Profile, Resume
from backend.schemas.profile import ProfileData, ProfileResponse, ProfileStatus, ProfileUpdateRequest, ResumeUploadResponse
from backend.services.profile.pdf_extractor import PdfTextExtractor
from backend.services.profile.profile_extractor import ProfileExtractor, get_profile_extractor


class ProfileService:
    def __init__(self, session: Session, extractor: ProfileExtractor | None = None) -> None:
        self.session = session
        self.extractor = extractor or get_profile_extractor()
        self.pdf_extractor = PdfTextExtractor()

    def upload_resume(self, filename: str | None, content_type: str | None, content: bytes) -> ResumeUploadResponse:
        self._validate_upload(filename, content_type, content)
        digest = hashlib.sha256(content).hexdigest()
        existing = self.session.scalar(select(Resume).where(Resume.sha256 == digest))
        if existing:
            self.session.execute(update(Resume).values(is_current=False))
            existing.is_current = True
            profile = self.session.scalar(select(Profile).where(Profile.resume_id == existing.id))
            self.session.commit()
            return ResumeUploadResponse(profile_id=profile.id, status=ProfileStatus(profile.status), resume_hash=digest, duplicate=True)

        settings = get_settings()
        extracted_text = self.pdf_extractor.extract(content, settings.min_resume_text_chars)
        stored_filename = f"{digest}.pdf"
        self._store_resume(settings.resume_storage_dir, stored_filename, content)
        try:
            self.session.execute(update(Resume).values(is_current=False))
            resume = Resume(stored_filename=stored_filename, original_filename=Path(filename or "resume.pdf").name, sha256=digest, file_size=len(content), text_length=len(extracted_text), is_current=True)
            self.session.add(resume)
            self.session.flush()
            profile = Profile(resume_id=resume.id, status=ProfileStatus.EXTRACTING.value, confirmed=False, data={})
            self.session.add(profile)
            self.session.flush()
            try:
                profile_data = self.extractor.extract(extracted_text)
                profile.data = profile_data.model_dump(mode="json")
                profile.status = ProfileStatus.REVIEW_REQUIRED.value
            except ProfileExtractionError:
                profile.status = ProfileStatus.ERROR.value
                self.session.commit()
                raise
            self.session.commit()
            return ResumeUploadResponse(profile_id=profile.id, status=ProfileStatus(profile.status), resume_hash=digest, duplicate=False)
        except Exception:
            self.session.rollback()
            raise

    def get_current_profile(self) -> ProfileResponse:
        resume = self.session.scalar(select(Resume).where(Resume.is_current.is_(True)).order_by(Resume.uploaded_at.desc()))
        if not resume:
            return ProfileResponse(status=ProfileStatus.EMPTY, confirmed=False)
        profile = self.session.scalar(select(Profile).where(Profile.resume_id == resume.id))
        return self._response(profile, resume)

    def update_current_profile(self, payload: ProfileUpdateRequest) -> ProfileResponse:
        profile, resume = self._current_entities()
        profile.data = payload.data.model_dump(mode="json")
        profile.confirmed = False
        profile.status = ProfileStatus.REVIEW_REQUIRED.value
        self.session.commit()
        self.session.refresh(profile)
        return self._response(profile, resume)

    def confirm_current_profile(self) -> ProfileResponse:
        profile, resume = self._current_entities()
        if ProfileStatus(profile.status) is not ProfileStatus.REVIEW_REQUIRED:
            raise ValidationError("A profile must be reviewed before it can be confirmed.")
        ProfileData.model_validate(profile.data)
        profile.confirmed = True
        profile.status = ProfileStatus.CONFIRMED.value
        self.session.commit()
        self.session.refresh(profile)
        return self._response(profile, resume)

    def _current_entities(self) -> tuple[Profile, Resume]:
        resume = self.session.scalar(select(Resume).where(Resume.is_current.is_(True)).order_by(Resume.uploaded_at.desc()))
        if not resume:
            raise ValidationError("Upload a resume before editing a profile.")
        profile = self.session.scalar(select(Profile).where(Profile.resume_id == resume.id))
        return profile, resume

    @staticmethod
    def _response(profile: Profile, resume: Resume) -> ProfileResponse:
        return ProfileResponse(id=profile.id, status=ProfileStatus(profile.status), confirmed=profile.confirmed, data=ProfileData.model_validate(profile.data), resume_hash=resume.sha256, original_filename=resume.original_filename, uploaded_at=resume.uploaded_at, updated_at=profile.updated_at)

    @staticmethod
    def _store_resume(directory: Path, filename: str, content: bytes) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / filename
        temporary = directory / f".{filename}.tmp"
        try:
            with temporary.open("wb") as file:
                file.write(content)
            os.replace(temporary, destination)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ValidationError("The resume could not be stored locally.") from exc

    @staticmethod
    def _validate_upload(filename: str | None, content_type: str | None, content: bytes) -> None:
        settings = get_settings()
        if not filename or Path(filename).suffix.lower() != ".pdf":
            raise ValidationError("Upload a PDF resume.")
        if content_type not in {"application/pdf", "application/x-pdf"}:
            raise ValidationError("The uploaded file must have a PDF content type.")
        if not content or len(content) > settings.max_resume_file_size_bytes:
            raise ValidationError("The resume file is empty or exceeds the 10 MB limit.")
        if not content.startswith(b"%PDF-"):
            raise ValidationError("The uploaded file is not a valid PDF.")
