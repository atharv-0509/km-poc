"""Deck / notes connector.

Parses a markdown-ish document into one record per section (a `##` heading
and the text beneath it). Used for the taxonomy deck and for minutes/notes.
Bullet lists under a heading stay with that heading's record.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator

from ..schema import Record

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def ingest_deck(path: str) -> Iterator[Record]:
    src = os.path.basename(path)
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()

    # Determine source_type from filename hints.
    lname = src.lower()
    if "minute" in lname or "meeting" in lname:
        stype = "minutes"
    elif "report" in lname:
        stype = "report"
    else:
        stype = "deck"

    section_title = os.path.splitext(src)[0]
    buf: list[str] = []
    page = 0
    emitted = False

    def flush(title: str, body_lines: list[str], page_no: int) -> Record | None:
        body = "\n".join(body_lines).strip()
        # Skip empty sections (e.g. the document's H1 title with no text under
        # it) so we don't emit contentless stub records.
        if not body:
            return None
        return Record(
            title=title.strip() or section_title,
            raw_text=(title + "\n" + body).strip(),
            source_file=src,
            row_or_page=f"section {page_no}",
            source_type=stype,
        )

    for line in lines:
        m = _HEADING.match(line)
        if m and len(m.group(1)) <= 2:  # new top/second-level section
            rec = flush(section_title, buf, page)
            if rec:
                yield rec
                emitted = True
            section_title = m.group(2)
            buf = []
            page += 1
        else:
            buf.append(line)

    rec = flush(section_title, buf, page)
    if rec:
        yield rec
        emitted = True

    if not emitted:  # whole-file fallback
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        yield Record(
            title=os.path.splitext(src)[0],
            raw_text=text,
            source_file=src,
            row_or_page="page 1",
            source_type=stype,
        )
