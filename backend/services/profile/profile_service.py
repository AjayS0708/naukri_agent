from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.exceptions import ProfileExtractionError, ValidationError
from backend.models.profile import Profile, Resume
from backend.schemas.profile import ProfileData, ProfileResponse, ProfileStatus, ProfileUpdateRequest, ResumeUploadResponse
from backend.services.profile.profile_extractor import ProfileExtractor, get_profile_extractor
from backend.services.profile.resume_service import ResumeService


class ProfileService:
    def __init__(self, session: Session, extractor: ProfileExtractor | None = None, resume_service: ResumeService | None = None) -> None:
        self.session = session
        self.extractor = extractor or get_profile_extractor()
        self.resume_service = resume_service or ResumeService()

    def upload_resume(self, filename: str | None, content_type: str | None, content: bytes) -> ResumeUploadResponse:
        self.resume_service.validate_upload(filename, content_type, content)
        digest = self._compute_hash(content)
        existing = self.session.scalar(select(Resume).where(Resume.sha256 == digest))
        if existing:
            self.session.execute(update(Resume).values(is_current=False))
            existing.is_current = True
            profile = self.session.scalar(select(Profile).where(Profile.resume_id == existing.id))
            self.session.commit()
            return ResumeUploadResponse(profile_id=profile.id, status=ProfileStatus(profile.status), resume_hash=digest, duplicate=True)

        processed = self.resume_service.process_upload(filename, content_type, content)
        try:
            self.session.execute(update(Resume).values(is_current=False))
            resume = Resume(
                stored_filename=processed.stored_filename,
                original_filename=processed.original_filename,
                sha256=processed.sha256,
                file_size=processed.file_size,
                text_length=len(processed.extracted_text),
                is_current=True,
            )
            self.session.add(resume)
            self.session.flush()
            profile = Profile(resume_id=resume.id, status=ProfileStatus.RESUME_UPLOADED.value, confirmed=False, data={})
            self.session.add(profile)
            self.session.flush()
            try:
                profile.status = ProfileStatus.EXTRACTING.value
                self.session.flush()
                profile_data = self._extract_profile_with_retry(processed.extracted_text)
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
        return ProfileResponse(
            id=profile.id,
            status=ProfileStatus(profile.status),
            confirmed=profile.confirmed,
            data=ProfileData.model_validate(profile.data),
            resume_hash=resume.sha256,
            original_filename=resume.original_filename,
            file_size=resume.file_size,
            uploaded_at=resume.uploaded_at,
            updated_at=profile.updated_at,
        )

    @staticmethod
    def _compute_hash(content: bytes) -> str:
        import hashlib

        return hashlib.sha256(content).hexdigest()

    def _extract_profile_with_retry(self, extracted_text: str) -> ProfileData:
        settings = get_settings()
        retries = max(0, settings.profile_extraction_retries)
        last_error: ProfileExtractionError | None = None
        for _ in range(retries + 1):
            try:
                return self.extractor.extract(extracted_text)
            except ProfileExtractionError as exc:
                last_error = exc
        raise last_error or ValidationError("Profile extraction failed.")
