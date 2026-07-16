"""Fixed vocabularies and the bilingual lexicon (Section 4: rule-based).

Nothing here uses a model. The department list, category keyword hints and
the cross-lingual lexicon are all hand-maintained reference data — exactly
the "department lookup from a fixed list" and "rule-based tagging" the plan
calls for.

The bilingual lexicon is the PoC stand-in for cross-lingual retrieval. In
production the self-hosted multilingual embedding model handles an English
query matching a Marathi record natively; here we expand known domain terms
to their translations so the dependency-free hashing embedder and the
keyword index can still bridge scripts. Add a row, gain a bridge.
"""

from __future__ import annotations

# Fixed department list (Section 6: "From a fixed department list").
DEPARTMENTS: tuple[str, ...] = (
    "General Administration",
    "Home",
    "Finance",
    "Urban Development",
    "Water Resources",
    "Water Supply & Sanitation",
    "Industries",
    "Information Technology",
    "Higher & Technical Education",
    "Public Works",
    "Health",
    "Agriculture",
    "Rural Development",
    "Energy",
    "Chief Minister's Office",
)

# Hints that map free text onto one of the 12 taxonomy categories.
# Each category lists trigger substrings (case-insensitive), including
# Marathi/Hindi variants so tagging works on multilingual rows.
CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "CM Meetings": ("cm meeting", "chief minister meeting", "मुख्यमंत्री बैठक", "मुख्यमंत्री बैठक"),
    "Announcements": ("announcement", "घोषणा", "जाहीर", "उद्घाटन"),
    "Cabinet Decisions": ("cabinet", "मंत्रिमंडळ", "कॅबिनेट", "मंत्रिमंडल"),
    "War Room": ("war room", "वॉर रूम", "वॉररूम"),
    "100/150 Days": ("100 days", "150 days", "100 दिवस", "150 दिवस"),
    "CEGIS": ("cegis",),
    "SAMAGRA": ("samagra", "समग्र"),
    "Databases": ("database", "dataset", "डेटाबेस", "डेटा"),
    "Conferences": ("conference", "summit", "परिषद", "संमेलन"),
    "Key Districts": ("district", "जिल्हा", "जिल्हे"),
    "PS Meetings": ("ps meeting", "principal secretary", "प्रधान सचिव"),
}

# Bilingual / cross-lingual lexicon. Each row groups equivalent terms across
# English, Marathi and Hindi. Query expansion and record alias-text both draw
# from these groups so an English question retrieves a Marathi record.
LEXICON: tuple[tuple[str, ...], ...] = (
    ("quantum", "क्वांटम", "क्वाण्टम"),
    ("semiconductor", "अर्धवाहक", "सेमीकंडक्टर", "सेमीकन्डक्टर"),
    ("manufacturing", "उत्पादन", "निर्माण", "विनिर्माण"),
    ("president", "राष्ट्रपती", "राष्ट्रपति"),
    ("prime minister", "पंतप्रधान", "प्रधानमंत्री"),
    ("chief minister", "मुख्यमंत्री"),
    ("governor", "राज्यपाल"),
    ("minister", "मंत्री"),
    ("letter", "पत्र", "पत्रव्यवहार"),
    ("meeting", "बैठक", "सभा"),
    ("water supply", "पाणीपुरवठा", "जलापूर्ति", "जल आपूर्ति"),
    ("water", "पाणी", "जल"),
    ("cabinet", "मंत्रिमंडळ", "मंत्रिमंडल", "कॅबिनेट"),
    ("decision", "निर्णय"),
    ("announcement", "घोषणा", "जाहीर"),
    ("inauguration", "उद्घाटन"),
    ("scheme", "योजना"),
    ("policy", "धोरण", "नीति"),
    ("district", "जिल्हा", "जिला"),
    ("road", "रस्ता", "सड़क", "मार्ग"),
    ("power", "वीज", "बिजली", "ऊर्जा"),
    ("electricity", "वीज", "बिजली"),
    ("investment", "गुंतवणूक", "निवेश"),
    ("industry", "उद्योग"),
    ("agriculture", "शेती", "कृषी", "कृषि"),
    ("farmer", "शेतकरी", "किसान"),
    ("health", "आरोग्य", "स्वास्थ्य"),
    ("education", "शिक्षण", "शिक्षा"),
    ("data centre", "डेटा सेंटर", "डेटा केंद्र"),
    ("summit", "परिषद", "शिखर परिषद"),
    ("war room", "वॉर रूम", "वॉररूम"),
)


def build_alias_index() -> dict[str, set[str]]:
    """Map every term (lowercased) to the full set of its group synonyms."""
    index: dict[str, set[str]] = {}
    for group in LEXICON:
        members = set(group)
        for term in group:
            index.setdefault(term.lower(), set()).update(members)
    return index


ALIAS_INDEX = build_alias_index()
