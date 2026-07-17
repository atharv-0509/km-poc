"""Excel (.xlsx/.xlsm) connector.

Reads every worksheet, fills merged-cell values across their span (so a merged
title cell doesn't leave blanks that confuse header detection), and reuses the
CSV connector's header-detection + record-shaping via `shape_rows`. One record
per data row, per sheet, with the sheet name captured for provenance.

Requires `openpyxl` (optional). Absent → the file is skipped with a warning.
"""

from __future__ import annotations

import datetime
import os
from collections.abc import Iterator

from ..schema import Record
from ._deps import optional_import
from .spreadsheet import _source_type_for, shape_rows


def _fmt_cell(v) -> str:
    """Render a cell value; dates/datetimes become clean ISO (no 00:00:00)."""
    if v is None:
        return ""
    if isinstance(v, datetime.datetime):
        if (v.hour, v.minute, v.second) == (0, 0, 0):
            return v.strftime("%Y-%m-%d")
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, datetime.date):
        return v.strftime("%Y-%m-%d")
    return str(v)


def _content_key(rec: Record):
    """A dedup key robust to extra/short columns: the set of substantive
    (long) cell values. None when the row has no substantive text."""
    vals = [
        " ".join(v.split()).lower()  # collapse newlines/spacing from merged fills
        for v in rec.extra.get("columns", {}).values()
        if isinstance(v, str)
    ]
    sig = tuple(sorted(v for v in vals if len(v) >= 10))
    return sig or None


def _fill_merged(ws) -> None:
    """Write each merged range's top-left value into every cell of the range,
    so the value is visible per-row even after we read the grid flat."""
    for rng in list(ws.merged_cells.ranges):
        top_left = ws.cell(row=rng.min_row, column=rng.min_col).value
        ws.unmerge_cells(str(rng))
        for row in range(rng.min_row, rng.max_row + 1):
            for col in range(rng.min_col, rng.max_col + 1):
                ws.cell(row=row, column=col).value = top_left


def _sheet_grid(ws) -> list[list[str]]:
    grid: list[list[str]] = []
    for row in ws.iter_rows(values_only=True):
        grid.append([_fmt_cell(v) for v in row])
    return grid


def ingest_xlsx(path: str) -> Iterator[Record]:
    openpyxl = optional_import("openpyxl", "openpyxl")
    if openpyxl is None:
        return

    src = os.path.basename(path)
    stype = _source_type_for(src)
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)

    seen_content: set[tuple] = set()
    try:
        for ws in wb.worksheets:
            _fill_merged(ws)
            grid = _sheet_grid(ws)
            if not any(any(c for c in r) for r in grid):
                continue  # empty sheet

            # Content-based row dedup across sheets — handles near-duplicate
            # sheets (e.g. 'Followup' ⊂ 'Sheet1') that a header/first-row
            # fingerprint misses because of column/offset differences.
            for rec in shape_rows(grid, src, ws.title, stype):
                key = _content_key(rec)
                if key is not None:
                    if key in seen_content:
                        continue
                    seen_content.add(key)
                yield rec
    finally:
        wb.close()
