"""Optional-dependency handling for format connectors.

XLSX/PDF/PPTX/DOCX each need a third-party library. Following the same pattern
as the embeddings backend, a connector degrades gracefully when its library is
absent: it warns once (to stderr) and skips the file, so a mixed directory
still ingests every format whose library IS installed. Install what you need
from requirements-optional.txt.
"""

from __future__ import annotations

import importlib
import sys

_warned: set[str] = set()


def optional_import(module: str, pip_name: str):
    """Return the imported module, or None (warning once) if unavailable."""
    try:
        return importlib.import_module(module)
    except Exception:
        if module not in _warned:
            _warned.add(module)
            print(
                f"[km] optional connector dependency '{module}' not installed; "
                f"skipping those files. Install with: pip install {pip_name}",
                file=sys.stderr,
            )
        return None
