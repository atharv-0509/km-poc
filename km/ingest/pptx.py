"""PowerPoint (.pptx) connector — the office "deck".

One record per slide: all shape/table text on the slide plus the slide's
presenter notes (often where the real substance lives). The slide title, when
present, becomes the record title. Slide number captured for provenance.

Requires `python-pptx` (optional). Absent → the file is skipped with a warning.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from ..schema import Record
from ._deps import optional_import


def _shape_text(shape) -> list[str]:
    out: list[str] = []
    if shape.has_text_frame:
        for para in shape.text_frame.paragraphs:
            line = "".join(run.text for run in para.runs).strip()
            if line:
                out.append(line)
    if shape.has_table:
        for row in shape.table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                out.append(" | ".join(cells))
    return out


def ingest_pptx(path: str) -> Iterator[Record]:
    pptx = optional_import("pptx", "python-pptx")
    if pptx is None:
        return

    src = os.path.basename(path)
    prs = pptx.Presentation(path)

    for i, slide in enumerate(prs.slides, start=1):
        lines: list[str] = []
        title = ""
        for shape in slide.shapes:
            texts = _shape_text(shape)
            if texts and not title and shape == slide.shapes.title:
                title = texts[0]
            lines.extend(texts)

        notes = ""
        if slide.has_notes_slide:
            notes = (slide.notes_slide.notes_text_frame.text or "").strip()
            if notes:
                lines.append("Notes: " + notes)

        body = "\n".join(lines).strip()
        if not body:
            continue
        yield Record(
            title=(title or lines[0])[:120],
            raw_text=body,
            source_file=src,
            row_or_page=f"slide {i}",
            source_type="deck",
            extra={"has_notes": bool(notes)},
        )
