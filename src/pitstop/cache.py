"""Atomic cache writes, source-fetch timestamps, and bounded download retries."""

from __future__ import annotations

import os
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0  # seconds; doubled between attempts


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


def _retryable(error: Exception) -> bool:
    """Whether a failed download is worth retrying (transient network or server)."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 429 or 500 <= error.code < 600
    return isinstance(error, (urllib.error.URLError, OSError))


def fetch_bytes(req: urllib.request.Request, timeout: int, attempts: int = RETRY_ATTEMPTS) -> bytes:
    """Download a URL, retrying transient failures with backoff. Raises the last error."""
    last: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError) as e:
            last = e
            if not _retryable(e) or attempt + 1 >= max(1, attempts):
                raise
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
    raise last  # pragma: no cover - loop always raises first
