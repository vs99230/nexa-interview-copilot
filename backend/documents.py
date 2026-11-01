"""Extract plain text from an uploaded resume (PDF, DOCX, TXT/MD)."""
from __future__ import annotations

import io
import re
from pathlib import Path

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
SUPPORTED = (".pdf", ".docx", ".txt", ".md")


class DocumentError(ValueError):
    """The uploaded document could not be read."""


def _tidy(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text(filename: str, data: bytes) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise DocumentError(f"Unsupported file type '{suffix or 'unknown'}'. Use PDF, DOCX or TXT.")

    try:
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        elif suffix == ".docx":
            from docx import Document

            doc = Document(io.BytesIO(data))
            lines = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    lines.append(" | ".join(cell.text.strip() for cell in row.cells))
            text = "\n".join(lines)
        else:
            text = data.decode("utf-8", errors="replace")
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError(f"Could not read '{filename}': {exc}") from exc

    text = _tidy(text)
    if len(text) < 30:
        raise DocumentError("No readable text found in the file (is it a scanned image?). Paste the text instead.")
    return text
