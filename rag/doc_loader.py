"""Document loading utilities for PDF/DOCX/TXT."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

MAX_DOC_SIZE_BYTES = 50 * 1024 * 1024  # 50MB


class DocumentLoader:
    @staticmethod
    def _meta(path: Path, page_count: int) -> dict:
        stat = path.stat()
        return {
            "filename": path.name,
            "filepath": str(path.resolve()),
            "page_count": page_count,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "size_bytes": stat.st_size,
        }

    def load(self, filepath: str) -> dict:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {filepath}")
        if path.stat().st_size > MAX_DOC_SIZE_BYTES:
            raise ValueError(
                f"Document too large: {path.stat().st_size} bytes exceeds {MAX_DOC_SIZE_BYTES} byte limit"
            )

        suffix = path.suffix.lower()

        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            meta = self._meta(path, page_count=len(reader.pages))
            return {"text": text, **meta}

        if suffix == ".docx":
            import docx

            doc = docx.Document(str(path))
            text = "\n".join(p.text for p in doc.paragraphs)
            meta = self._meta(path, page_count=1)
            return {"text": text, **meta}

        text = path.read_text(encoding="utf-8", errors="ignore")
        meta = self._meta(path, page_count=1)
        return {"text": text, **meta}
