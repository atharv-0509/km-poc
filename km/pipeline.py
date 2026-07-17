"""End-to-end orchestration: ingest → tag → index, and search.

Ties the four stages together. Keeps the CLI and web layers thin.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from .config import Config
from .embeddings import get_embedder
from .ingest import ingest_dir, ingest_path
from .schema import Record
from .search import SearchResult, hybrid_search
from .store import Store
from .tagging import tag


def open_store(cfg: Config) -> Store:
    embedder = get_embedder(cfg.embedder)
    return Store(cfg.db_path, embedder)


def _tagged(records: Iterator[Record]) -> Iterator[Record]:
    for rec in records:
        yield tag(rec)


def build_index(cfg: Config, target: str | None = None, reset: bool = True) -> dict:
    """Ingest a path (file or dir), tag, and index. Returns a summary."""
    path = target or cfg.data_dir
    if reset and os.path.exists(cfg.db_path):
        os.remove(cfg.db_path)

    store = open_store(cfg)
    if os.path.isdir(path):
        source = ingest_dir(path)
    else:
        source = ingest_path(path)

    n = store.add_many(_tagged(source))

    by_lang: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for rec in store.all_records():
        by_lang[rec.language] = by_lang.get(rec.language, 0) + 1
        by_cat[rec.category] = by_cat.get(rec.category, 0) + 1
        by_type[rec.source_type] = by_type.get(rec.source_type, 0) + 1

    summary = {
        "indexed": n,
        "embedder": store.embedder.name,
        "db": cfg.db_path,
        "by_language": by_lang,
        "by_category": by_cat,
        "by_source_type": by_type,
    }
    store.close()
    return summary


def build_index_gdrive(
    cfg: Config, folder_id: str, creds_path: str | None = None,
    recursive: bool = True, reset: bool = False,
) -> dict:
    """Pull a Google Drive folder (service account), tag and index it."""
    from .ingest.gdrive import ingest_gdrive

    if reset and os.path.exists(cfg.db_path):
        os.remove(cfg.db_path)

    store = open_store(cfg)
    source = ingest_gdrive(folder_id, creds_path=creds_path, recursive=recursive)
    n = store.add_many(_tagged(source))
    summary = {"indexed": n, "embedder": store.embedder.name,
               "db": cfg.db_path, "folder_id": folder_id}
    store.close()
    return summary


def search(
    cfg: Config, query: str, limit: int = 10, filters: dict | None = None,
    answer: bool | None = None,
) -> SearchResult:
    store = open_store(cfg)
    try:
        return hybrid_search(
            store, query, limit=limit, filters=filters,
            answer=cfg.answer if answer is None else answer,
        )
    finally:
        store.close()
