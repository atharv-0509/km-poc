"""Optional final answer step (Section 4: OFF by default).

Two modes, both local and cheap:

* extractive (default when answering is requested): NO model at all. Composes
  a 2-line answer purely from the top records' titles/snippets and their
  citations. Zero token cost, fully deterministic.

* llm: a small, local, open-weight model phrases a 2-line summary over the
  retrieved snippets. Wired behind a lazy import; if no local model is
  configured it degrades to the extractive answer. Never calls a paid API.

The whole system works with this turned off — you just get ranked records.
"""

from __future__ import annotations

import os

# Guarded so the module imports even without the search module at type-check.
try:  # pragma: no cover - typing convenience
    from .search import Hit
except Exception:  # pragma: no cover
    Hit = object  # type: ignore


def summarise(query: str, hits: list, mode: str | None = None) -> str:
    mode = mode or os.environ.get("KM_ANSWER_MODE", "extractive")
    if not hits:
        return "No records matched this query."
    if mode == "llm":
        text = _llm_summary(query, hits)
        if text:
            return text
    return _extractive_summary(query, hits)


def _extractive_summary(query: str, hits: list) -> str:
    top = hits[0]
    n = len(hits)
    lead = top.record.title.strip()
    cite = top.record.provenance
    others = ""
    if n > 1:
        others = f" {n - 1} further related record(s) also matched."
    return (
        f"Top match: {lead} [{cite}].{others} "
        f"Returned {n} record(s) with sources; review the citations below."
    )


def _llm_summary(query: str, hits: list) -> str | None:
    """Attempt a local open-weight LLM summary. Returns None if unavailable."""
    model_path = os.environ.get("KM_LOCAL_LLM")
    if not model_path:
        return None
    try:  # pragma: no cover - exercised only with a real local model
        from llama_cpp import Llama

        llm = Llama(model_path=model_path, n_ctx=2048, verbose=False)
        context = "\n".join(
            f"- {h.record.title} [{h.record.provenance}]: {h.snippet}"
            for h in hits[:5]
        )
        prompt = (
            "You are answering from retrieved government records. In at most "
            "two sentences, answer the question using ONLY the records below, "
            "and do not invent facts.\n\n"
            f"Question: {query}\n\nRecords:\n{context}\n\nAnswer:"
        )
        out = llm(prompt, max_tokens=120, temperature=0.2, stop=["\n\n"])
        return out["choices"][0]["text"].strip() or None
    except Exception:
        return None
