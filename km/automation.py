"""Free, zero-dependency automation: watch a source and re-index on change.

A background loop fingerprints the data folder (paths + sizes + mtimes) and,
whenever it changes, rebuilds the index. The web UI reads the index file fresh
on every query, so a rebuilt index is picked up with no restart — drop a file
in, watch it become searchable. Standard library only; nothing to pay for.

The same loop drives periodic Google Drive re-pulls (`km gdrive --watch`),
which is likewise free — the Drive API has no per-call charge.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

from .config import Config
from .pipeline import build_index, build_index_gdrive


def _fingerprint(root: str) -> tuple:
    """Cheap change signal for a directory tree: (path, size, mtime) per file."""
    items = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if name.startswith("."):
                continue
            p = os.path.join(dirpath, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            items.append((p, st.st_size, int(st.st_mtime)))
    return tuple(items)


def watch_local(
    cfg: Config,
    interval: float = 2.0,
    once: bool = False,
    on_update: Callable[[dict], None] | None = None,
    stop: threading.Event | None = None,
) -> None:
    """Poll cfg.data_dir; rebuild the index whenever its contents change."""
    last: tuple | None = None
    while not (stop and stop.is_set()):
        fp = _fingerprint(cfg.data_dir)
        if fp != last:
            summary = build_index(cfg)
            summary["at"] = time.strftime("%H:%M:%S")
            if on_update:
                on_update(summary)
            else:
                print(f"[{summary['at']}] reindexed: {summary['indexed']} records "
                      f"in {cfg.data_dir}")
            last = fp
        if once:
            return
        time.sleep(interval)


def watch_gdrive(
    cfg: Config, folder_id: str, creds_path: str | None = None,
    interval: float = 300.0, on_update: Callable[[dict], None] | None = None,
    stop: threading.Event | None = None,
) -> None:
    """Periodically re-pull a Drive folder and rebuild the index (free)."""
    while not (stop and stop.is_set()):
        summary = build_index_gdrive(cfg, folder_id, creds_path=creds_path, reset=True)
        summary["at"] = time.strftime("%H:%M:%S")
        (on_update or (lambda s: print(
            f"[{s['at']}] Drive re-pull: {s['indexed']} records")))(summary)
        for _ in range(int(interval)):
            if stop and stop.is_set():
                return
            time.sleep(1)


def start_background_watch(cfg: Config, interval: float = 2.0) -> threading.Event:
    """Launch watch_local in a daemon thread; return an Event to stop it."""
    stop = threading.Event()
    t = threading.Thread(
        target=watch_local, args=(cfg,), kwargs={"interval": interval, "stop": stop},
        daemon=True,
    )
    t.start()
    return stop
