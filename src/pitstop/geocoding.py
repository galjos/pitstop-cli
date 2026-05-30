"""Second data source: authoritative Italian comune coordinates, used to
validate MIMIT station coordinates. Self-contained centroid heuristics in
`core` cannot catch mis-geocoded stations in single-station comuni (e.g.
RASUN-ANTERSELVA), so a true comune→(lat, lon) reference is required.

Source: opendatasicilia/comuni-italiani `main.csv`, derived from ISTAT.
Runtime fetch + local cache; no redistribution."""

from __future__ import annotations

import csv
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

COMUNI_URL = (
    "https://raw.githubusercontent.com/opendatasicilia/comuni-italiani/main/dati/main.csv"
)
COMUNI_SOURCE_NAME = "opendatasicilia/comuni-italiani (ISTAT-derived)"

DEFAULT_COMUNI_MAX_AGE = 30 * 24 * 60 * 60  # 30 days; comuni change rarely
DEFAULT_TIMEOUT = 180


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    d = Path(base) / "pitstop"
    d.mkdir(parents=True, exist_ok=True)
    return d


def normalize_comune(name: str) -> str:
    """Uppercase, trim, collapse internal whitespace. MIMIT uses uppercase
    names; opendatasicilia uses capitalized — uppercase makes both match."""
    return " ".join(name.strip().upper().split())


def _cached_path(refresh: bool, max_age: int, timeout: int) -> Path | None:
    path = _cache_dir() / "comuni_main.csv"
    if not refresh and path.exists():
        if max_age <= 0 or (time.time() - path.stat().st_mtime) < max_age:
            return path
    try:
        req = urllib.request.Request(COMUNI_URL, headers={"User-Agent": "pitstop"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError) as e:
        # Graceful fallback: if we cannot fetch, return any stale cache or None.
        print(f"pitstop: could not fetch comune coordinates ({e}); "
              f"falling back to self-contained heuristics", file=sys.stderr)
        return path if path.exists() else None
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def load_comune_coords(
    *,
    refresh: bool = False,
    max_age: int = DEFAULT_COMUNI_MAX_AGE,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, tuple[float, float]]:
    """Return {normalized_comune_name: (lat, lon)}. Empty dict on fetch failure
    with no cache, so callers should treat it as best-effort."""
    path = _cached_path(refresh, max_age, timeout)
    if path is None:
        return {}
    return _parse_comuni(path)


def _parse_comuni(path: Path) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("comune", "").strip()
            if not name:
                continue
            try:
                lat = float(row["lat"])
                lon = float(row["long"])
            except (KeyError, ValueError, TypeError):
                continue
            out[normalize_comune(name)] = (lat, lon)
    return out
