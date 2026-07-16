"""Rule-based tagging — Stage 2 of the architecture.

Date parsing, category inference, department lookup and entity/location
extraction. All regex and fixed-list lookups: "No LLM per record."
Given a raw record with title + text + provenance, `tag()` fills in the
metadata fields of the Section 6 schema.
"""

from __future__ import annotations

import re

from .lang import detect_language, expand_terms
from .schema import Record
from .vocab import CATEGORY_HINTS, DEPARTMENTS

# --- Dates -----------------------------------------------------------------

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# 2025-06-14 / 2025/06/14
_ISO = re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b")
# 14-06-2025 / 14/06/2025 / 14.06.2025
_DMY = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")
# 14 June 2025 / 14 Jun 2025 / June 14, 2025
_DMY_TEXT = re.compile(
    r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b|\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b"
)


def parse_date(text: str) -> str | None:
    """Return the first parseable date as ISO YYYY-MM-DD, or None."""
    if not text:
        return None

    m = _ISO.search(text)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return _fmt(y, mo, d)

    m = _DMY.search(text)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        return _fmt(y, mo, d)

    m = _DMY_TEXT.search(text)
    if m:
        if m.group(1):
            d, mon, y = m.group(1), m.group(2), m.group(3)
        else:
            mon, d, y = m.group(4), m.group(5), m.group(6)
        mo = _MONTHS.get(mon.lower())
        if mo:
            return _fmt(int(y), mo, int(d))
    return None


def _fmt(y: int, mo: int, d: int) -> str | None:
    if not (1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


# --- Department & category -------------------------------------------------

def infer_department(text: str) -> str | None:
    lowered = (text or "").lower()
    for dept in DEPARTMENTS:
        if dept.lower() in lowered:
            return dept
    # Common shorthands.
    if "gad" in lowered or "general administration" in lowered:
        return "General Administration"
    if "cmo" in lowered:
        return "Chief Minister's Office"
    return None


def infer_category(text: str, hint: str | None = None) -> str:
    """Assign one of the 12 taxonomy categories from keyword hints.

    `hint` is an optional source-level nudge (e.g. the sheet or file already
    tells us the category), checked first.
    """
    haystack = f"{hint or ''}\n{text or ''}".lower()
    for category, triggers in CATEGORY_HINTS.items():
        for trig in triggers:
            if trig.lower() in haystack:
                return category
    return "Uncategorised"


# --- Entities & locations --------------------------------------------------

# A small gazetteer of Maharashtra places for the PoC. In production this is a
# fixed reference list / gazetteer lookup, still no model involved.
_PLACES = (
    "Mumbai", "Pune", "Nagpur", "Nashik", "Aurangabad", "Chhatrapati Sambhajinagar",
    "Thane", "Amravati", "Solapur", "Kolhapur", "Ratnagiri", "Gadchiroli",
    "New Delhi", "Delhi", "मुंबई", "पुणे", "नागपूर", "नाशिक", "दिल्ली",
)

# Titled people / orgs: "Shri X", "Hon'ble Y", "President", "PM", etc.
_TITLE = re.compile(
    r"\b(?:Hon'?ble|Shri|Smt\.?|Dr\.?|Mr\.?|Ms\.?|President|Governor|"
    r"Prime Minister|Chief Minister|Minister|Secretary)\s+[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+)*"
)


def extract_locations(text: str) -> list[str]:
    found = []
    for place in _PLACES:
        if place in (text or ""):
            found.append(place)
    return _dedupe(found)


def extract_entities(text: str) -> list[str]:
    return _dedupe(m.group(0).strip() for m in _TITLE.finditer(text or ""))


def _dedupe(items) -> list[str]:
    seen: dict[str, None] = {}
    for it in items:
        if it and it not in seen:
            seen[it] = None
    return list(seen)


# --- Orchestration ---------------------------------------------------------

def tag(record: Record, category_hint: str | None = None) -> Record:
    """Fill in every rule-tagged metadata field on `record` in place."""
    basis = f"{record.title}\n{record.raw_text}"

    if not record.date:
        record.date = parse_date(basis)
    record.language = detect_language(basis)
    if not record.department:
        record.department = infer_department(basis)
    if record.category == "Uncategorised":
        record.category = infer_category(basis, hint=category_hint)
    if not record.location:
        record.location = extract_locations(basis)
    if not record.entities:
        record.entities = extract_entities(basis)

    aliases = expand_terms(basis)
    record.alias_text = " ".join(aliases)
    return record
