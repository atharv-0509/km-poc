"""Stage 4 — Retrieve & answer. Hybrid search with citations.

Keyword (exact IDs, dates, names) and semantic (meaning, cross-lingual)
results are fused with Reciprocal Rank Fusion (RRF). RRF needs no score
calibration between the two very different scales — it just combines ranks —
which is what makes hybrid search robust in practice.

Every hit carries its full provenance (file · sheet · row/page) so answers
are always traceable to a source. The optional LLM summary sits on top and is
off by default; with it off you get ranked records with snippets, which the
plan states is a complete, valid answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from .lang import expand_terms, tokenize
from .schema import Record
from .store import Store

RRF_K = 60  # standard RRF damping constant
# Keyword is weighted above the vector list in fusion. The dependency-free
# hashing embedder is noisy on real data (char n-grams conflate e.g.
# "president"/"prisons"), so exact/field-aware keyword evidence should lead;
# with a real multilingual model the two are naturally more balanced.
KEYWORD_WEIGHT = 2.0
VECTOR_WEIGHT = 1.0


@dataclass
class Hit:
    record: Record
    score: float
    keyword_rank: int | None
    vector_rank: int | None
    snippet: str

    @property
    def why(self) -> str:
        signals = []
        if self.keyword_rank is not None:
            signals.append(f"keyword#{self.keyword_rank}")
        if self.vector_rank is not None:
            signals.append(f"semantic#{self.vector_rank}")
        return "+".join(signals) or "—"


@dataclass
class SearchResult:
    query: str
    hits: list[Hit]
    answer: str | None = None


def _rrf(ranked_ids: list[str]) -> dict[str, float]:
    return {rid: 1.0 / (RRF_K + i + 1) for i, rid in enumerate(ranked_ids)}


def _snippet(record: Record, query: str, width: int = 220) -> str:
    """Return a short excerpt around the best-matching query term."""
    text = " ".join(record.raw_text.split())
    if not text:
        return record.title
    terms = set(tokenize(query)) | set(expand_terms(query))
    low = text.lower()
    pos = -1
    for t in terms:
        if len(t) < 2:
            continue
        p = low.find(t)
        if p != -1 and (pos == -1 or p < pos):
            pos = p
    if pos == -1:
        return text[:width] + ("…" if len(text) > width else "")
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def hybrid_search(
    store: Store,
    query: str,
    limit: int = 10,
    filters: dict | None = None,
    pool: int = 30,
    answer: bool = False,
) -> SearchResult:
    kw = store.keyword_search(query, limit=pool, filters=filters)
    vec = store.vector_search(query, limit=pool, filters=filters)

    kw_ids = [rid for rid, _ in kw]
    vec_ids = [rid for rid, _ in vec]
    kw_rank = {rid: i for i, rid in enumerate(kw_ids)}
    vec_rank = {rid: i for i, rid in enumerate(vec_ids)}

    fused: dict[str, float] = {}
    for rid, s in _rrf(kw_ids).items():
        fused[rid] = fused.get(rid, 0.0) + KEYWORD_WEIGHT * s
    for rid, s in _rrf(vec_ids).items():
        fused[rid] = fused.get(rid, 0.0) + VECTOR_WEIGHT * s

    ranked = sorted(fused.items(), key=lambda t: t[1], reverse=True)[:limit]

    hits: list[Hit] = []
    for rid, score in ranked:
        rec = store.get(rid)
        if rec is None:
            continue
        hits.append(
            Hit(
                record=rec,
                score=score,
                keyword_rank=(kw_rank[rid] + 1) if rid in kw_rank else None,
                vector_rank=(vec_rank[rid] + 1) if rid in vec_rank else None,
                snippet=_snippet(rec, query),
            )
        )

    result = SearchResult(query=query, hits=hits)
    if answer:
        from .answer import summarise
        result.answer = summarise(query, hits)
    return result
