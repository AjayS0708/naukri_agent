from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.profile import ProfileResponse, ProfileUpdateRequest, ResumeUploadResponse
from backend.services.profile.profile_service import ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])


@router.post("/resume", response_model=ResumeUploadResponse, status_code=201)
async def upload_resume(resume: UploadFile = File(...), db: Session = Depends(get_db)) -> ResumeUploadResponse:
    content = await resume.read()
    return ProfileService(db).upload_resume(resume.filename, resume.content_type, content)


@router.get("", response_model=ProfileResponse)
def get_profile(db: Session = Depends(get_db)) -> ProfileResponse:
    return ProfileService(db).get_current_profile()


@router.put("", response_model=ProfileResponse)
def update_profile(payload: ProfileUpdateRequest, db: Session = Depends(get_db)) -> ProfileResponse:
    return ProfileService(db).update_current_profile(payload)


@router.post("/confirm", response_model=ProfileResponse)
def confirm_profile(db: Session = Depends(get_db)) -> ProfileResponse:
    return ProfileService(db).confirm_current_profile()
