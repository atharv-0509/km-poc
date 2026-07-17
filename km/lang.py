"""Language detection and cross-lingual expansion — rule-based, no model.

Language detection is script-based: we count Devanagari vs Latin characters
and use a small stop-word signal to separate Marathi from Hindi (both use
Devanagari). This is deliberately simple and fully offline, matching the
plan's "language auto-detected" metadata field without an LLM.
"""

from __future__ import annotations

import re

from .vocab import ALIAS_INDEX

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")
_WORD = re.compile(r"[\wऀ-ॿ]+", re.UNICODE)

# Words that appear in Marathi but not (or rarely) in Hindi, and vice versa.
# Enough signal to disambiguate the two Devanagari languages for the PoC.
_MARATHI_MARKERS = {"आणि", "आहे", "आहेत", "यांची", "यांच्या", "साठी", "मध्ये", "नाही", "व", "बैठक"}
_HINDI_MARKERS = {"और", "है", "हैं", "के", "की", "में", "नहीं", "पत्र", "को"}


def detect_language(text: str) -> str:
    """Return one of: 'mar', 'hin', 'eng', 'mixed', 'und'."""
    if not text or not text.strip():
        return "und"

    deva = len(_DEVANAGARI.findall(text))
    latin = len(_LATIN.findall(text))
    total = deva + latin
    if total == 0:
        return "und"

    deva_ratio = deva / total
    tokens = set(_WORD.findall(text))

    has_deva = deva_ratio > 0.15
    has_latin = (latin / total) > 0.15

    if has_deva and has_latin:
        return "mixed"

    if has_deva:
        mar = len(tokens & _MARATHI_MARKERS)
        hin = len(tokens & _HINDI_MARKERS)
        if mar > hin:
            return "mar"
        if hin > mar:
            return "hin"
        # Default Devanagari to Marathi — this office's records skew Marathi.
        return "mar"

    return "eng"


def tokenize(text: str) -> list[str]:
    """Lowercased word tokens across Latin and Devanagari scripts."""
    return [t.lower() for t in _WORD.findall(text or "")]


# Function words that match nearly every record and only dilute keyword
# ranking. Kept small and high-precision (English + common Marathi/Hindi).
STOPWORDS = {
    "the", "a", "an", "to", "in", "on", "of", "for", "and", "or", "is", "are",
    "was", "were", "be", "with", "at", "by", "from", "as", "that", "this",
    "show", "me", "all", "everything", "about", "what", "which", "who", "list",
    "give", "find", "get", "letter", "letters", "regarding", "request", "please",
    "व", "आणि", "मध्ये", "साठी", "आहे", "यांना", "का", "की", "के", "में", "और",
    "को", "है", "पत्र",
}


def content_terms(text: str) -> list[str]:
    """Query tokens worth matching on: drop stopwords and bare numbers/years
    (dates are handled by the date filter, not keyword OR-terms)."""
    out = []
    for t in tokenize(text):
        if len(t) < 2 or t in STOPWORDS or t.isdigit():
            continue
        out.append(t)
    return out


def expand_terms(text: str) -> list[str]:
    """Cross-lingual expansion: for every known term in `text`, add all of
    its lexicon synonyms. Also expands multi-word terms (e.g. 'water supply').

    Returns the list of *added* alias terms (not the originals), so callers
    can store them separately as alias_text.
    """
    if not text:
        return []
    lowered = text.lower()
    added: set[str] = set()

    # Single tokens.
    for tok in set(tokenize(text)):
        for syn in ALIAS_INDEX.get(tok, ()):  # type: ignore[arg-type]
            added.add(syn)

    # Multi-word phrases present in the lexicon.
    for phrase, syns in ALIAS_INDEX.items():
        if " " in phrase and phrase in lowered:
            added.update(syns)

    # Do not echo terms already present verbatim.
    present = set(tokenize(text))
    return sorted(a for a in added if a.lower() not in present)
