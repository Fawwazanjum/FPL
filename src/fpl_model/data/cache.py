from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class TtlCache:
    """File-based JSON cache. Key = hash of (endpoint, params)."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_key(endpoint: str, params: dict | None = None) -> str:
        raw = endpoint + "|" + json.dumps(params or {}, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _payload_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _meta_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.meta.json"

    def get(self, key: str, ttl_hours: float) -> Any | None:
        payload_path = self._payload_path(key)
        meta_path = self._meta_path(key)
        if not payload_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            fetched_at = meta["fetched_at"]
        except (ValueError, KeyError, OSError):
            return None
        if time.time() - fetched_at > ttl_hours * 3600:
            return None
        try:
            return json.loads(payload_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    def set(self, key: str, payload: Any) -> None:
        self._payload_path(key).write_text(json.dumps(payload), encoding="utf-8")
        self._meta_path(key).write_text(json.dumps({"fetched_at": time.time()}), encoding="utf-8")

    def force_stale(self, key: str) -> None:
        meta_path = self._meta_path(key)
        if meta_path.exists():
            meta_path.unlink()
