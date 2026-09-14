import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from backend.core.config import get_settings
from backend.core.exceptions import ValidationError
from backend.services.profile.pdf_extractor import PdfTextExtractor


@dataclass(frozen=True)
class ResumeProcessingResult:
    sha256: str
    stored_filename: str
    original_filename: str
    file_size: int
    extracted_text: str


class ResumeService:
    def __init__(self, pdf_extractor: PdfTextExtractor | None = None) -> None:
        self.pdf_extractor = pdf_extractor or PdfTextExtractor()

    def process_upload(self, filename: str | None, content_type: str | None, content: bytes) -> ResumeProcessingResult:
        self.validate_upload(filename, content_type, content)
        digest = hashlib.sha256(content).hexdigest()
        settings = get_settings()
        extracted_text = self.pdf_extractor.extract(content, settings.min_resume_text_chars)
        stored_filename = f"{digest}.pdf"
        self.store_resume(settings.resume_storage_dir, stored_filename, content)
        return ResumeProcessingResult(
            sha256=digest,
            stored_filename=stored_filename,
            original_filename=Path(filename or "resume.pdf").name,
            file_size=len(content),
            extracted_text=extracted_text,
        )

    @staticmethod
    def validate_upload(filename: str | None, content_type: str | None, content: bytes) -> None:
        settings = get_settings()
        if not filename or Path(filename).suffix.lower() != ".pdf":
            raise ValidationError("Upload a PDF resume.")
        if content_type not in {"application/pdf", "application/x-pdf"}:
            raise ValidationError("The uploaded file must have a PDF content type.")
        if not content or len(content) > settings.max_resume_file_size_bytes:
            raise ValidationError("The resume file is empty or exceeds the 10 MB limit.")
        if not content.startswith(b"%PDF-"):
            raise ValidationError("The uploaded file is not a valid PDF.")

    @staticmethod
    def store_resume(directory: Path, filename: str, content: bytes) -> None:
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
