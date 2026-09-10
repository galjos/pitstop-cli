"""Atomic cache writes and source-fetch timestamps."""

from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", delete=False) as f:
            name = f.name
            f.write(data)
        os.replace(name, path)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def file_metadata(path: Path, status: str | None = None) -> dict:
    return fetch_metadata(path.stat().st_mtime, status)


def fetch_metadata(fetched: float, status: str | None = None) -> dict:
    result = {
        "fetched_at": datetime.fromtimestamp(fetched, timezone.utc).isoformat(),
        "age_seconds": max(0, int(time.time() - fetched)),
    }
    if status is not None:
        result["cache_status"] = status
    return result
