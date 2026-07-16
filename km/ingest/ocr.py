"""Scan / OCR connector — Stage 1 for image-only records.

Production path: Tesseract with Marathi/Hindi/English language packs
(`pytesseract`, `lang="mar+hin+eng"`), fully local, no LLM. If Tesseract is
not installed, the connector falls back to reading a sidecar text file
(`<image>.ocr.txt`) or, for `.txt` scans, the text itself — so the pipeline
is demonstrable end-to-end without the binary present. The rest of the system
never knows which path produced the text.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from ..schema import Record

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pdf")


def _tesseract_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        import shutil
        return shutil.which("tesseract") is not None
    except Exception:
        return False


def _ocr_image(path: str) -> str:
    import pytesseract
    from PIL import Image

    if path.lower().endswith(".pdf"):
        # Left as an explicit extension point for a PDF rasteriser.
        raise NotImplementedError("PDF rasterisation not wired in the PoC")
    return pytesseract.image_to_string(Image.open(path), lang="mar+hin+eng")


def _read_text_source(path: str) -> str | None:
    """Get OCR text without the binary: sidecar first, then plain-text scan."""
    sidecar = os.path.splitext(path)[0] + ".ocr.txt"
    if os.path.exists(sidecar):
        with open(sidecar, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    if path.lower().endswith(".txt"):
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return None


def ingest_scan(path: str) -> Iterator[Record]:
    src = os.path.basename(path)
    text: str | None = None
    engine = "sidecar/plain-text"

    if path.lower().endswith(_IMAGE_EXTS) and _tesseract_available():
        try:
            text = _ocr_image(path)
            engine = "tesseract(mar+hin+eng)"
        except Exception:
            text = None

    if text is None:
        text = _read_text_source(path)

    if not text or not text.strip():
        return  # nothing recoverable; skip silently

    # A scanned page is one record; title = first non-empty line.
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), src)
    yield Record(
        title=first_line[:120],
        raw_text=text,
        source_file=src,
        row_or_page="page 1",
        source_type="scan",
        extra={"ocr_engine": engine},
    )
