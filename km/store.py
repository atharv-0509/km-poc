"""Stage 3 — Index. Keyword (FTS5) + vector store in one SQLite file.

Three things live together in a single, portable DB file:
  * `records`  — the canonical tagged records (Section 6 schema, as JSON)
  * `fts`      — an FTS5 full-text index for exact terms / IDs (BM25 ranked)
  * `vectors`  — one embedding per record for semantic search

The vector search here is an exact brute-force cosine over packed float
vectors — perfectly adequate for a PoC's volume and fully self-contained.
The production swap is a one-file change: point `vector_search` at Qdrant or
pgvector in the same GCP project/region. The keyword and record layers are
unchanged.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from collections.abc import Iterable

from .embeddings import Embedder, cosine
from .lang import content_terms, expand_terms, tokenize
from .schema import Record

_FILTERABLE = ("date", "language", "department", "category", "source_type")


class Store:
    def __init__(self, path: str, embedder: Embedder) -> None:
        self.path = path
        self.embedder = embedder
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    # --- schema ---
    def _init_schema(self) -> None:
        c = self.conn
        c.execute(
            """CREATE TABLE IF NOT EXISTS records (
                   id TEXT PRIMARY KEY,
                   date TEXT, language TEXT, department TEXT,
                   category TEXT, source_type TEXT,
                   json TEXT NOT NULL
               )"""
        )
        c.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5("
            "  id UNINDEXED, title, recipient, keys, body, tokenize='unicode61')"
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS vectors (
                   id TEXT PRIMARY KEY, dim INTEGER, vec BLOB,
                   embedder TEXT
               )"""
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)"
        )
        c.execute(
            "INSERT OR REPLACE INTO meta(k, v) VALUES('embedder', ?)",
            (self.embedder.name,),
        )
        c.commit()

    # --- write ---
    def add(self, record: Record) -> None:
        c = self.conn
        c.execute(
            "INSERT OR REPLACE INTO records(id,date,language,department,"
            "category,source_type,json) VALUES(?,?,?,?,?,?,?)",
            (record.id, record.date, record.language, record.department,
             record.category, record.source_type, record.to_json()),
        )
        c.execute("DELETE FROM fts WHERE id=?", (record.id,))
        # recipient/keys carry the aboutness fields PLUS the cross-lingual
        # aliases of *those fields only* — so a recipient "राष्ट्रपती" matches an
        # English "president" query without body terms leaking into the
        # high-weight columns and diluting field-aware ranking.
        c.execute(
            "INSERT INTO fts(id,title,recipient,keys,body) VALUES(?,?,?,?,?)",
            (record.id, record.title,
             _with_aliases(record.recipient), _with_aliases(record.key_fields),
             record.search_text()),
        )
        vec = self.embedder.embed(record.search_text())
        c.execute(
            "INSERT OR REPLACE INTO vectors(id,dim,vec,embedder) VALUES(?,?,?,?)",
            (record.id, len(vec), _pack(vec), self.embedder.name),
        )

    def add_many(self, records: Iterable[Record]) -> int:
        n = 0
        for r in records:
            self.add(r)
            n += 1
        self.conn.commit()
        return n

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

    def get(self, rec_id: str) -> Record | None:
        row = self.conn.execute(
            "SELECT json FROM records WHERE id=?", (rec_id,)
        ).fetchone()
        return Record.from_dict(json.loads(row["json"])) if row else None

    # --- read / search ---
    def keyword_search(
        self, query: str, limit: int = 20, filters: dict | None = None
    ) -> list[tuple[str, float]]:
        """FTS5/BM25 keyword search. Returns [(id, score)] best-first.

        The query is tokenised and cross-lingually expanded, so exact IDs and
        English↔Marathi term matches both hit the keyword index.
        """
        terms = set(content_terms(query)) | set(expand_terms(query))
        terms = {t for t in terms if len(t) >= 2}
        if not terms:
            # Query was all stopwords/numbers — fall back to raw tokens.
            terms = {t for t in tokenize(query) if len(t) >= 2}
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in sorted(terms))

        where, params = self._filter_sql(filters)
        # Weight columns (id, title, recipient, keys, body): the recipient
        # dominates (a letter addressed to the President beats one whose subject
        # merely says "...as President of..."), then subject/topic, then title,
        # then incidental body mentions.
        sql = (
            "SELECT f.id AS id, bm25(fts, 0.0, 6.0, 16.0, 8.0, 1.0) AS rank FROM fts f "
            "JOIN records r ON r.id = f.id "
            "WHERE fts MATCH ? " + where + " ORDER BY rank LIMIT ?"
        )
        rows = self.conn.execute(sql, [match, *params, limit]).fetchall()
        # bm25() returns lower=better; flip to higher=better for fusion.
        return [(row["id"], -float(row["rank"])) for row in rows]

    def vector_search(
        self, query: str, limit: int = 20, filters: dict | None = None
    ) -> list[tuple[str, float]]:
        """Brute-force cosine over stored embeddings. Returns [(id, score)]."""
        qvec = self.embedder.embed(_expand_query_text(query))
        where, params = self._filter_sql(filters)
        sql = (
            "SELECT v.id AS id, v.vec AS vec FROM vectors v "
            "JOIN records r ON r.id = v.id WHERE 1=1 " + where
        )
        scored: list[tuple[str, float]] = []
        for row in self.conn.execute(sql, params):
            scored.append((row["id"], cosine(qvec, _unpack(row["vec"]))))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:limit]

    def _filter_sql(self, filters: dict | None) -> tuple[str, list]:
        if not filters:
            return "", []
        clauses, params = [], []
        for key, val in filters.items():
            if key not in _FILTERABLE or val is None:
                continue
            if key == "date" and isinstance(val, (list, tuple)) and len(val) == 2:
                clauses.append("r.date BETWEEN ? AND ?")
                params.extend(val)
            else:
                clauses.append(f"r.{key} = ?")
                params.append(val)
        where = (" AND " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def all_records(self) -> list[Record]:
        rows = self.conn.execute("SELECT json FROM records").fetchall()
        return [Record.from_dict(json.loads(r["json"])) for r in rows]

    def close(self) -> None:
        self.conn.close()


def _with_aliases(text: str) -> str:
    """Append a field's own cross-lingual aliases to it (for the weighted
    recipient/keys FTS columns)."""
    if not text:
        return ""
    aliases = expand_terms(text)
    return text + ("  " + " ".join(aliases) if aliases else "")


def _expand_query_text(query: str) -> str:
    """Append cross-lingual aliases to the query before embedding it, so the
    hashing embedder can bridge scripts the way the multilingual model would.
    """
    aliases = expand_terms(query)
    return query + (" " + " ".join(aliases) if aliases else "")


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))
