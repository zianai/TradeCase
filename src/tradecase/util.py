"""Small deterministic serialization and safety helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(data) -> bytes:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def no_symlinks(path: Path) -> None:
    for item in [path, *path.parents]:
        if item.is_symlink():
            raise ValueError(f"symlink path is not allowed: {item.name}")
