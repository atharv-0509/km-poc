"""Spreadsheet connector with real header-row detection.

The sample files confirmed messy, human-built structure: headers on row 2 or
3, merged title cells, duplicate column names, near-duplicate sheets. Naive
"row 1 is the header" parsing fails. This connector scans the first several
rows and scores each as a candidate header, then emits one clean record per
data row below it.

CSV is used for the PoC (dependency-free). A production connector for .xlsx
plugs in behind the same `ingest_spreadsheet` signature; the header-detection
and record-shaping logic is unchanged.
"""

from __future__ import annotations

import csv
import os
import re
from collections.abc import Iterator

from ..schema import Record, TAXONOMY

_MAX_HEADER_SCAN = 6  # how many leading rows to consider as header candidates

# Column names that hold an explicit category value we should trust over
# free-text keyword inference (a real category column beats a header word that
# merely happens to contain "घोषणा").
_CATEGORY_COLUMNS = ("प्रवर्ग", "वर्ग", "category", "प्रकार", "type")
_TAXONOMY_LOWER = {t.lower(): t for t in TAXONOMY}


def _explicit_category(pairs: dict[str, str]) -> str | None:
    """If a column names the category and its value maps to the taxonomy,
    return the canonical category; else None."""
    for col, val in pairs.items():
        if any(hint in col.lower() for hint in _CATEGORY_COLUMNS):
            canon = _TAXONOMY_LOWER.get(val.strip().lower())
            if canon:
                return canon
    return None


def _score_header(row: list[str], following: list[list[str]]) -> float:
    """Heuristic score: a good header row is mostly non-empty short labels,
    is not numeric/date-like, and is followed by rows with similar arity.
    """
    cells = [c.strip() for c in row]
    non_empty = [c for c in cells if c]
    if len(non_empty) < 2:
        return 0.0

    filled = len(non_empty) / len(cells)

    # Labels are usually short-ish and not pure numbers.
    labelish = 0
    for c in non_empty:
        if len(c) <= 40 and not c.replace(".", "").replace("-", "").isdigit():
            labelish += 1
    labelish_ratio = labelish / len(non_empty)

    # Reward when the rows below have the same number of populated columns.
    width = len(cells)
    consistent = 0
    for r in following[:4]:
        if r and abs(len([c for c in r if c.strip()]) - len(non_empty)) <= 1:
            consistent += 1
    consistency = consistent / max(1, len(following[:4]))

    return filled * 0.4 + labelish_ratio * 0.4 + consistency * 0.2


def _dedupe_headers(headers: list[str]) -> list[str]:
    """Handle duplicate / empty column names deterministically."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, h in enumerate(headers):
        name = h.strip() or f"col{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out.append(name)
    return out


def detect_header(rows: list[list[str]]) -> int:
    """Return the index of the most likely header row (0-based)."""
    best_idx, best_score = 0, -1.0
    for i in range(min(_MAX_HEADER_SCAN, len(rows))):
        score = _score_header(rows[i], rows[i + 1:])
        if score > best_score:
            best_idx, best_score = i, score
    return best_idx


def _sheet_name(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _source_type_for(name: str) -> str:
    """Infer the record type from the file name (letters register vs tracker)."""
    low = name.lower()
    if "letter" in low or "correspond" in low or "register" in low:
        return "letter"
    if "minute" in low:
        return "minutes"
    return "tracker"


def shape_rows(
    rows: list[list[str]], src: str, sheet: str, stype: str
) -> Iterator[Record]:
    """Turn a raw 2D grid into clean records: detect the real header row,
    dedupe columns, and emit one record per populated data row.

    Shared by the CSV connector and the XLSX connector so header detection and
    record shaping behave identically regardless of the file format.
    """
    if not rows:
        return
    hidx = detect_header(rows)
    headers = _dedupe_headers([str(c) for c in rows[hidx]])
    ncols = len(headers)

    for r, row in enumerate(rows[hidx + 1:], start=hidx + 2):  # 1-based row no.
        cells = [str(c).strip() for c in row]
        if not any(cells):
            continue  # skip blank rows
        # Pad/truncate to header width.
        cells = (cells + [""] * ncols)[:ncols]
        pairs = {h: v for h, v in zip(headers, cells) if v}
        if not pairs:
            continue

        title = _pick_title(pairs)
        body = "\n".join(f"{h}: {v}" for h, v in pairs.items())

        yield Record(
            title=title,
            raw_text=body,
            source_file=src,
            sheet=sheet,
            row_or_page=f"row {r}",
            source_type=stype,
            category=_explicit_category(pairs) or "Uncategorised",
            key_fields=_key_fields(pairs),
            extra={"columns": pairs},
        )


# Column headers that carry the record's "aboutness" (who it's to / what it's
# about) — weighted above the rest of the row in keyword ranking.
_KEY_COLUMNS = (
    "subject", "विषय", "तपशील", "घोषणा", "addressed", "recipient", "to ",
    "नाव", "name", "particulars", "title", "स्थळ", "place",
)


def _key_fields(pairs: dict[str, str]) -> str:
    picked = [
        v for h, v in pairs.items()
        if v and any(k in h.lower() for k in _KEY_COLUMNS)
    ]
    return "  ".join(picked)


def ingest_spreadsheet(path: str) -> Iterator[Record]:
    src = os.path.basename(path)
    sheet = _sheet_name(path)
    stype = _source_type_for(src)

    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        rows = list(csv.reader(fh))
    yield from shape_rows(rows, src, sheet, stype)


_DATEISH = re.compile(r"^\s*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\s*$")


def _pick_title(pairs: dict[str, str]) -> str:
    """Choose a human-readable title from the row's populated cells."""
    preferred = (
        "subject", "title", "विषय", "तपशील", "घोषणा", "particulars",
        "description", "recipient", "name", "नाव",
    )
    lowered = {k.lower(): k for k in pairs}
    for want in preferred:
        for lk, orig in lowered.items():
            if want in lk and pairs[orig]:
                return pairs[orig]
    # Fall back to the first value that is not a bare number or a date.
    for v in pairs.values():
        if len(v) > 3 and not v.isdigit() and not _DATEISH.match(v):
            return v
    return next(iter(pairs.values()))
