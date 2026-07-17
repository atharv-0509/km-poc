"""Command-line interface for the Knowledge Management PoC.

    python -m km ingest [PATH]      build the index from data/ (or PATH)
    python -m km query "..."        hybrid search; --answer for a summary
    python -m km gdrive FOLDER_ID   pull + index a Google Drive folder
    python -m km demo               run the Section 8 representative queries
    python -m km serve              start the thin web search UI
    python -m km stats              show what's in the index
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import load
from .pipeline import build_index, build_index_gdrive, open_store, search

# ANSI helpers (fall back to plain if not a TTY).
def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


def _print_result(result, show_why: bool = True) -> None:
    if result.answer:
        print(_c("1;36", "\nAnswer: ") + result.answer)
    if not result.hits:
        print(_c("33", "\nNo records matched.\n"))
        return
    print()
    for i, hit in enumerate(result.hits, 1):
        r = hit.record
        head = f"{i}. {r.title}"
        print(_c("1", head))
        meta = f"   {r.category} · {r.source_type} · {r.language}"
        if r.date:
            meta += f" · {r.date}"
        if r.department:
            meta += f" · {r.department}"
        print(_c("2", meta))
        print(f"   {_c('2', 'source:')} {r.provenance}")
        print(f"   {hit.snippet}")
        if show_why:
            print(_c("2", f"   match: {hit.why}  score={hit.score:.4f}"))
        print()


def cmd_ingest(args) -> int:
    cfg = load()
    if args.embedder:
        cfg.embedder = args.embedder
    summary = build_index(cfg, target=args.path, reset=not args.append)
    print(_c("1;32", f"Indexed {summary['indexed']} records") +
          f" into {summary['db']}")
    print(f"  embedder:    {summary['embedder']}")
    print(f"  by language: {summary['by_language']}")
    print(f"  by category: {summary['by_category']}")
    print(f"  by type:     {summary['by_source_type']}")
    return 0


def _parse_filters(items: list[str] | None) -> dict:
    filters: dict = {}
    for it in items or []:
        if "=" not in it:
            continue
        k, v = it.split("=", 1)
        filters[k.strip()] = v.strip()
    return filters


def cmd_query(args) -> int:
    cfg = load()
    if args.embedder:
        cfg.embedder = args.embedder
    filters = _parse_filters(args.filter)
    result = search(cfg, args.query, limit=args.limit, filters=filters,
                    answer=args.answer)
    if args.json:
        print(json.dumps(
            {
                "query": result.query,
                "answer": result.answer,
                "hits": [
                    {
                        "title": h.record.title,
                        "provenance": h.record.provenance,
                        "category": h.record.category,
                        "language": h.record.language,
                        "date": h.record.date,
                        "score": h.score,
                        "why": h.why,
                        "snippet": h.snippet,
                    }
                    for h in result.hits
                ],
            },
            ensure_ascii=False, indent=2,
        ))
    else:
        _print_result(result)
    return 0


DEMO_QUERIES = [
    ("Show me everything on Quantum", None),
    ("What meetings on semiconductor manufacturing?", None),
    ("Letters to the President in 2025", {"date": ["2025-01-01", "2025-12-31"]}),
    ("War room announcements about water supply", None),
    ("Cabinet decisions on SAMAGRA", None),
]


def cmd_demo(args) -> int:
    cfg = load()
    store = open_store(cfg)
    count = store.count()
    store.close()
    if count == 0:
        print(_c("33", "Index is empty — building it first..."))
        build_index(cfg)
    print(_c("1;36", f"\nRunning {len(DEMO_QUERIES)} representative queries "
                     f"(Section 8). answer={cfg.answer or args.answer}\n"))
    for q, filt in DEMO_QUERIES:
        print(_c("1;34", "═" * 72))
        print(_c("1;34", f"Q: {q}") + (f"   filter={filt}" if filt else ""))
        result = search(cfg, q, limit=args.limit, filters=filt,
                        answer=args.answer or cfg.answer)
        _print_result(result, show_why=True)
    return 0


def cmd_gdrive(args) -> int:
    cfg = load()
    if args.embedder:
        cfg.embedder = args.embedder
    summary = build_index_gdrive(
        cfg, args.folder_id, creds_path=args.credentials,
        recursive=not args.no_recursive, reset=not args.append,
    )
    print(_c("1;32", f"Pulled + indexed {summary['indexed']} records") +
          f" from Drive folder {summary['folder_id']}")
    print(f"  embedder: {summary['embedder']}  db: {summary['db']}")
    return 0


def cmd_stats(args) -> int:
    cfg = load()
    store = open_store(cfg)
    recs = store.all_records()
    store.close()
    by_lang, by_cat, by_type, by_dept = {}, {}, {}, {}
    for r in recs:
        by_lang[r.language] = by_lang.get(r.language, 0) + 1
        by_cat[r.category] = by_cat.get(r.category, 0) + 1
        by_type[r.source_type] = by_type.get(r.source_type, 0) + 1
        if r.department:
            by_dept[r.department] = by_dept.get(r.department, 0) + 1
    print(f"records:    {len(recs)}")
    print(f"languages:  {by_lang}")
    print(f"categories: {by_cat}")
    print(f"types:      {by_type}")
    print(f"departments:{by_dept}")
    return 0


def cmd_serve(args) -> int:
    from .web import serve
    cfg = load()
    serve(cfg)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="km", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="ingest + tag + index a path")
    pi.add_argument("path", nargs="?", default=None, help="file or dir (default: data/)")
    pi.add_argument("--append", action="store_true", help="add to existing index")
    pi.add_argument("--embedder", choices=["auto", "hashing", "sentence-transformers"])
    pi.set_defaults(func=cmd_ingest)

    pq = sub.add_parser("query", help="hybrid search")
    pq.add_argument("query")
    pq.add_argument("-n", "--limit", type=int, default=10)
    pq.add_argument("-f", "--filter", action="append",
                    help="metadata filter, e.g. -f language=mar -f category='Cabinet Decisions'")
    pq.add_argument("--answer", action="store_true", help="add the optional summary")
    pq.add_argument("--json", action="store_true")
    pq.add_argument("--embedder", choices=["auto", "hashing", "sentence-transformers"])
    pq.set_defaults(func=cmd_query)

    pd = sub.add_parser("demo", help="run the representative queries")
    pd.add_argument("-n", "--limit", type=int, default=5)
    pd.add_argument("--answer", action="store_true")
    pd.set_defaults(func=cmd_demo)

    pg = sub.add_parser("gdrive", help="pull + index a Google Drive folder (service account)")
    pg.add_argument("folder_id", help="Drive folder id (shared with the service account)")
    pg.add_argument("-c", "--credentials", help="path to service-account JSON key "
                    "(or set KM_GDRIVE_CREDENTIALS)")
    pg.add_argument("--no-recursive", action="store_true", help="do not descend into subfolders")
    pg.add_argument("--append", action="store_true", help="add to existing index")
    pg.add_argument("--embedder", choices=["auto", "hashing", "sentence-transformers"])
    pg.set_defaults(func=cmd_gdrive)

    ps = sub.add_parser("stats", help="show index contents")
    ps.set_defaults(func=cmd_stats)

    pv = sub.add_parser("serve", help="start the web search UI")
    pv.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
