"""Thin Overpass-API client with on-disk caching. Used by `chargers.py` to
fetch OpenStreetMap charging-station nodes. Standard library only.

OSM data is licensed ODbL — `pitstop` runtime-fetches only and attributes the
source in its output. No redistribution."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SOURCE_NAME = "OpenStreetMap (via Overpass API)"
SOURCE_URL = "https://www.openstreetmap.org/copyright"

DEFAULT_MAX_AGE = 7 * 24 * 60 * 60  # 7 days — charger metadata moves slowly
DEFAULT_TIMEOUT = 60


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    d = Path(base) / "pitstop" / "overpass"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:24]


def fetch_elements(
    query: str,
    *,
    refresh: bool = False,
    max_age: int = DEFAULT_MAX_AGE,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[list[dict], str | None]:
    """Run an Overpass QL query and return (elements, error_msg).

    error_msg is None on success, or a string describing the failure.
    If a failure occurs but a stale cache exists, elements are returned
    from cache and error_msg is still set."""
    path = _cache_dir() / f"{_cache_key(query)}.json"
    if not refresh and path.exists():
        if max_age <= 0 or (time.time() - path.stat().st_mtime) < max_age:
            return _read(path), None

    req = urllib.request.Request(
        OVERPASS_URL,
        data=query.encode("utf-8"),
        headers={"User-Agent": "pitstop/0.7 (https://github.com/galjos/pitstop-cli)"},
        method="POST",
    )
    error = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError) as e:
        error = str(e)
        print(f"pitstop: Overpass fetch failed ({error}); "
              f"{'using stale cache' if path.exists() else 'no data available'}",
              file=sys.stderr)
        return (_read(path) if path.exists() else []), error

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return _read(path), None


def _read(path: Path) -> list[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("elements", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError):
        return []
