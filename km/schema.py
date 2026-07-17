"""The record schema — Section 6 of the approach plan.

This dataclass IS the contract between the two halves of the system
(ingestion/knowledge layer and retrieval/interface layer). Every source
connector must emit records that conform to this shape; the index and
search layers consume only this shape. Lock this first, build the rest
independently.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


# The 12 top-level taxonomy categories from the office's deck (Section 2).
# The plan enumerates 11 by name; "Uncategorised" is the catch-all 12th used
# when rule-based tagging cannot confidently assign one of the named values.
TAXONOMY: tuple[str, ...] = (
    "CM Meetings",
    "Announcements",
    "Cabinet Decisions",
    "War Room",
    "100/150 Days",
    "CEGIS",
    "SAMAGRA",
    "Databases",
    "Conferences",
    "Key Districts",
    "PS Meetings",
    "Uncategorised",
)

SOURCE_TYPES: tuple[str, ...] = (
    "tracker",
    "letter",
    "minutes",
    "deck",
    "report",
    "scan",
    "unknown",
)

LANGUAGES: tuple[str, ...] = ("mar", "hin", "eng", "mixed", "und")


@dataclass
class Record:
    """One clean, tagged record — the atom of the whole system.

    Fields map one-to-one onto the Section 6 metadata standard. `raw_text`
    carries the full text used for both embedding and keyword search;
    everything else is provenance and rule-extracted metadata used for
    filtering, ranking and trust.
    """

    # --- Content ---
    title: str                     # human-readable record name / subject
    raw_text: str                  # full text for embedding + keyword search

    # --- Provenance (Section 6: exact provenance for trust) ---
    source_file: str               # originating file name
    sheet: str | None = None       # sheet name, for spreadsheets
    row_or_page: str | None = None # row number or page number
    source_type: str = "unknown"   # tracker / letter / minutes / deck / scan …

    # --- Rule-tagged metadata ---
    date: str | None = None        # normalised ISO date (YYYY-MM-DD) if found
    language: str = "und"          # mar / hin / eng / mixed (auto-detected)
    department: str | None = None  # from the fixed department list
    category: str = "Uncategorised"  # one of the 12 taxonomy values
    location: list[str] = field(default_factory=list)  # place names
    entities: list[str] = field(default_factory=list)  # people / orgs

    # --- Retrieval aids (not part of the human-facing contract) ---
    # Cross-lingual alias text: original terms expanded to their
    # translations so both the keyword and (fallback) vector index can
    # bridge languages even without a multilingual embedding model.
    alias_text: str = ""
    # The "aboutness" fields — recipient / subject / who-and-what — that a
    # connector identified. Weighted above body text in keyword ranking so
    # "letters to the President" matches the recipient, not a stray mention.
    key_fields: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = self.compute_id()

    def compute_id(self) -> str:
        """Stable id from provenance + title, so re-ingesting is idempotent."""
        basis = "|".join(
            str(x)
            for x in (self.source_file, self.sheet, self.row_or_page, self.title)
        )
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    @property
    def provenance(self) -> str:
        """Compact, human-readable citation string."""
        parts = [self.source_file]
        if self.sheet:
            parts.append(f"sheet '{self.sheet}'")
        if self.row_or_page:
            parts.append(self.row_or_page)
        return " · ".join(parts)

    def search_text(self) -> str:
        """Everything that should be full-text/embedding searchable."""
        chunks = [self.title, self.raw_text, self.alias_text]
        chunks.extend(self.location)
        chunks.extend(self.entities)
        return "\n".join(c for c in chunks if c)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Record":
        known = {f: d.get(f) for f in cls.__dataclass_fields__ if f in d}
        return cls(**known)
