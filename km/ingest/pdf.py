"""PDF connector — text PDFs and scanned (image-only) PDFs.

For each page: extract the embedded text. If a page has (almost) no extractable
text it is treated as a scan — the page is rasterised and passed to the local
OCR path (Tesseract mar+hin+eng) when available. One record per page, with the
page number captured for provenance.

Requires `pymupdf` (fitz) for text/rasterisation (optional). Absent → the file
is skipped with a warning.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from ..schema import Record
from ._deps import optional_import

_MIN_TEXT_CHARS = 20  # below this, treat the page as scanned and try OCR


def _source_type_for(name: str) -> str:
    low = name.lower()
    if "minute" in low or "meeting" in low:
        return "minutes"
    if "letter" in low:
        return "letter"
    if "report" in low:
        return "report"
    return "report"


def _ocr_page(page) -> str:
    """Rasterise a page and OCR it, if Tesseract is available; else ''. """
    from .ocr import _tesseract_available

    if not _tesseract_available():
        return ""
    try:
        import pytesseract
        from PIL import Image
        import io

        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img, lang="mar+hin+eng")
    except Exception:
        return ""


def ingest_pdf(path: str) -> Iterator[Record]:
    fitz = optional_import("fitz", "pymupdf")
    if fitz is None:
        return

    src = os.path.basename(path)
    stype = _source_type_for(src)
    doc = fitz.open(path)
    try:
        for i, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            engine = "text-layer"
            if len(text) < _MIN_TEXT_CHARS:
                ocr = _ocr_page(page)
                if ocr.strip():
                    text, engine = ocr, "tesseract(mar+hin+eng)"
            if not text.strip():
                continue
            first_line = next(
                (ln.strip() for ln in text.splitlines() if ln.strip()), src
            )
            yield Record(
                title=first_line[:120],
                raw_text=text,
                source_file=src,
                row_or_page=f"page {i}",
                source_type="scan" if engine.startswith("tesseract") else stype,
                extra={"extractor": engine},
            )
    finally:
        doc.close()
