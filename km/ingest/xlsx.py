"""Excel (.xlsx/.xlsm) connector.

Reads every worksheet, fills merged-cell values across their span (so a merged
title cell doesn't leave blanks that confuse header detection), and reuses the
CSV connector's header-detection + record-shaping via `shape_rows`. One record
per data row, per sheet, with the sheet name captured for provenance.

Requires `openpyxl` (optional). Absent → the file is skipped with a warning.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from ..schema import Record
from ._deps import optional_import
from .spreadsheet import _source_type_for, shape_rows


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
        grid.append(["" if v is None else str(v) for v in row])
    return grid


def ingest_xlsx(path: str) -> Iterator[Record]:
    openpyxl = optional_import("openpyxl", "openpyxl")
    if openpyxl is None:
        return

    src = os.path.basename(path)
    stype = _source_type_for(src)
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)

    seen_fingerprints: set[tuple] = set()
    try:
        for ws in wb.worksheets:
            _fill_merged(ws)
            grid = _sheet_grid(ws)
            if not any(any(c for c in r) for r in grid):
                continue  # empty sheet

            # Skip near-duplicate sheets (same header + first data row).
            fp = tuple(tuple(r) for r in grid[:3])
            if fp in seen_fingerprints:
                continue
            seen_fingerprints.add(fp)

            yield from shape_rows(grid, src, ws.title, stype)
    finally:
        wb.close()
