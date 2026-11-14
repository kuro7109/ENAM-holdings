"""Tiny on-disk cache for API responses: one JSON file per (url, params).

Keeps dev loops fast and stops us hammering NSE/BSE while iterating. `use_cached=False`
(the --force flag) skips reads but still writes, so the next normal run is warm.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .config import ROOT


class JsonCache:
    def __init__(self, directory: str | Path = ROOT / ".cache" / "http",
                 ttl_seconds: int = 1800, use_cached: bool = True):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds
        self.use_cached = use_cached

    def _path(self, url: str, params: dict | None) -> Path:
        key = json.dumps([url, sorted((params or {}).items())], default=str)
        return self.dir / f"{hashlib.sha1(key.encode()).hexdigest()}.json"

    def get(self, url: str, params: dict | None = None) -> Any | None:
        if not self.use_cached:
            return None
        p = self._path(url, params)
        if not p.exists():
            return None
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - blob.get("saved_at", 0) > self.ttl:
            return None
        return blob.get("data")

    def set(self, url: str, params: dict | None, data: Any) -> None:
        p = self._path(url, params)
        p.write_text(json.dumps({"saved_at": time.time(), "url": url, "params": params, "data": data},
                                ensure_ascii=False), encoding="utf-8")
