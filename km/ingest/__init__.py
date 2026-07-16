"""Stage 1 — Ingest & normalise. One connector per source type.

Every connector yields raw `Record`s (title, raw_text, provenance,
source_type) that the tagging stage then enriches. Connectors do NOT tag;
that keeps ingestion and the knowledge layer cleanly separable.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from ..schema import Record
from .deck import ingest_deck
from .ocr import ingest_scan
from .spreadsheet import ingest_spreadsheet


def ingest_path(path: str) -> Iterator[Record]:
    """Dispatch a single file to the right connector by extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".tsv"):
        yield from ingest_spreadsheet(path)
    elif ext in (".md", ".markdown", ".txt"):
        # Decks/notes as markdown; scans arrive as .txt sidecars via ingest_scan.
        if os.path.basename(path).startswith("scan") or ".ocr" in os.path.basename(path):
            yield from ingest_scan(path)
        else:
            yield from ingest_deck(path)
    elif ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pdf"):
        yield from ingest_scan(path)
    else:
        # Unknown type: index as a single plain-text record so nothing is lost.
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        yield Record(
            title=os.path.basename(path),
            raw_text=text,
            source_file=os.path.basename(path),
            source_type="unknown",
        )


def ingest_dir(root: str) -> Iterator[Record]:
    """Walk a directory and ingest every supported file."""
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if name.startswith("."):
                continue
            yield from ingest_path(os.path.join(dirpath, name))
