"""Word (.docx) connector — minutes, letters, reports.

Splits the document into records by Heading-styled paragraphs (one record per
section, keeping its body and any tables). Documents with no headings become a
single record. Source type is inferred from the file name (letter / minutes /
report).

Requires `python-docx` (optional). Absent → the file is skipped with a warning.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from ..schema import Record
from ._deps import optional_import


def _source_type_for(name: str) -> str:
    low = name.lower()
    if "letter" in low or "correspond" in low:
        return "letter"
    if "minute" in low or "meeting" in low:
        return "minutes"
    return "report"


def _iter_block_text(document) -> Iterator[tuple[bool, str]]:
    """Yield (is_heading, text) for each paragraph, then table rows as body."""
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name or "").lower() if para.style else ""
        yield style.startswith("heading") or style == "title", text
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                yield False, " | ".join(cells)


def ingest_docx(path: str) -> Iterator[Record]:
    docx = optional_import("docx", "python-docx")
    if docx is None:
        return

    src = os.path.basename(path)
    stype = _source_type_for(src)
    document = docx.Document(path)

    section_title = os.path.splitext(src)[0]
    buf: list[str] = []
    idx = 0

    def make(title: str, body_lines: list[str], n: int) -> Record | None:
        body = "\n".join(body_lines).strip()
        if not body:
            return None
        return Record(
            title=(title or body_lines[0])[:120],
            raw_text=(title + "\n" + body).strip(),
            source_file=src,
            row_or_page=f"section {n}",
            source_type=stype,
        )

    for is_heading, text in _iter_block_text(document):
        if is_heading:
            rec = make(section_title, buf, idx)
            if rec:
                yield rec
            section_title = text
            buf = []
            idx += 1
        else:
            buf.append(text)

    rec = make(section_title, buf, idx)
    if rec:
        yield rec
