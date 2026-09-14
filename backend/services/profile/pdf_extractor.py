import re

import pymupdf

from backend.core.exceptions import ValidationError


class PdfTextExtractor:
    def extract(self, content: bytes, minimum_chars: int) -> str:
        try:
            document = pymupdf.open(stream=content, filetype="pdf")
        except (pymupdf.FileDataError, RuntimeError) as exc:
            raise ValidationError("The uploaded file is not a readable PDF.") from exc
        try:
            text = "\n".join(page.get_text("text") for page in document)
        finally:
            document.close()
        normalized = re.sub(r"\s+", " ", text).strip()
        if len(normalized) < minimum_chars:
            raise ValidationError("The PDF does not contain enough readable resume text.")
        return normalized
