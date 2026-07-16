"""Runtime configuration. Env-overridable; sensible PoC defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    db_path: str = os.environ.get("KM_DB", "km_index.sqlite3")
    data_dir: str = os.environ.get("KM_DATA", "data")
    embedder: str = os.environ.get("KM_EMBEDDER", "auto")  # auto|hashing|sentence-transformers
    answer: bool = os.environ.get("KM_ANSWER", "0") == "1"  # LLM/answer step OFF by default
    host: str = os.environ.get("KM_HOST", "127.0.0.1")
    port: int = int(os.environ.get("KM_PORT", "8080"))


def load() -> Config:
    return Config()
