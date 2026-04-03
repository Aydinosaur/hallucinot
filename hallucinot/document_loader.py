from __future__ import annotations

from io import BytesIO

from docx import Document
from pypdf import PdfReader


def extract_text(filename: str, payload: bytes) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix == "txt":
        return payload.decode("utf-8", errors="ignore")
    if suffix == "docx":
        return _extract_docx(payload)
    if suffix == "pdf":
        return _extract_pdf(payload)
    raise ValueError(f"Unsupported file type: {suffix}")


def _extract_docx(payload: bytes) -> str:
    document = Document(BytesIO(payload))
    parts = [paragraph.text for paragraph in document.paragraphs]
    return "\n".join(part for part in parts if part.strip())


def _extract_pdf(payload: bytes) -> str:
    reader = PdfReader(BytesIO(payload))
    parts: list[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(page_text)
    return "\n\n".join(parts)
