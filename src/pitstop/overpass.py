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

from .cache import fetch_bytes, file_metadata, write_atomic
from .validation import validate_download
from .version import __version__

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
    metadata: dict | None = None,
) -> tuple[list[dict], str | None]:
    """Run an Overpass QL query and return (elements, error_msg).

    error_msg is None on success, or a string describing the failure.
    If a failure occurs but a stale cache exists, elements are returned
    from cache and error_msg is still set. Optional metadata receives the fetch
    timestamp, cache age, and cache status for this response."""
    validate_download(timeout, max_age)
    path = _cache_dir() / f"{_cache_key(query)}.json"
    try:
        cached_data = path.read_bytes()
    except OSError:
        cached_data = b""
    cache_valid = _unusable_reason(cached_data) is None
    cached = _elements_of(cached_data) if cache_valid else []
    if metadata is not None:
        metadata.clear()
    def describe(status: str, from_cache: bool = True) -> None:
        if metadata is not None:
            metadata.update(file_metadata(path, status) if from_cache and path.exists()
                            else {"cache_status": status})

    if not refresh and cache_valid:
        if max_age <= 0 or (time.time() - path.stat().st_mtime) < max_age:
            describe("hit")
            return cached, None

    req = urllib.request.Request(
        OVERPASS_URL,
        data=query.encode("utf-8"),
        headers={"User-Agent": f"pitstop/{__version__} (https://github.com/galjos/pitstop-cli)"},
        method="POST",
    )
    error = None
    try:
        data = fetch_bytes(req, timeout)
    except (urllib.error.URLError, OSError) as e:
        error = str(e)
        print(f"pitstop: Overpass fetch failed ({error}); "
              f"{'using stale cache' if cache_valid else 'no data available'}",
              file=sys.stderr)
        describe("stale_fallback" if cache_valid else "unavailable", cache_valid)
        return cached, error

    # Overpass reports runtime failures as HTTP 200 with a `remark` in an otherwise
    # well-formed body, sometimes with a partial element set. Caching one would
    # replace a good cache and then serve "0 chargers, no error" for max_age.
    error = _unusable_reason(data)
    if error is not None:
        # Nothing cached: whatever the failed body carried beats zero chargers.
        elements = cached if cache_valid else _elements_of(data)
        if cache_valid:
            fallback = "using stale cache"
        elif elements:
            fallback = f"returning {len(elements)} partial element(s), not cached"
        else:
            fallback = "no data available"
        print(f"pitstop: Overpass returned no usable data ({error}); {fallback}",
              file=sys.stderr)
        describe("stale_fallback" if cache_valid else "partial" if elements else "unavailable", cache_valid)
        return elements, error

    write_atomic(path, data)
    describe("miss")
    return _read(path), None


# Overpass also emits benign remarks, so match failure wording, not the key itself.
_ERROR_REMARK_MARKERS = ("error", "timed out", "timeout", "out of memory", "exceeded")


def _unusable_reason(data: bytes) -> str | None:
    """Why this response body must not be cached, or None if it is usable."""
    try:
        parsed = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return f"response was not valid JSON: {e}"
    if not isinstance(parsed, dict):
        return "response was not a JSON object"
    if not isinstance(parsed.get("elements"), list) or any(
        not isinstance(element, dict) for element in parsed["elements"]
    ):
        return "response did not contain a valid elements list"
    remark = str(parsed.get("remark", "")).strip()
    if remark and any(m in remark.lower() for m in _ERROR_REMARK_MARKERS):
        return f"Overpass remark: {remark}"
    return None


def _elements_of(data: bytes) -> list[dict]:
    """Elements carried by a response body, or [] if it has none or does not parse."""
    try:
        parsed = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    elements = parsed.get("elements") if isinstance(parsed, dict) else None
    return [element for element in elements if isinstance(element, dict)] if isinstance(elements, list) else []


def _read(path: Path) -> list[dict]:
    try:
        data = path.read_bytes()
        if _unusable_reason(data) is not None:
            return []
        return _elements_of(data)
    except OSError:
        return []
