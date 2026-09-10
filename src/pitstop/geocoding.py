"""Second data source: Italian comune reference coordinates, used to
validate MIMIT station coordinates. Self-contained centroid heuristics in
`core` cannot catch mis-geocoded stations in single-station comuni (e.g.
RASUN-ANTERSELVA). Reference coordinates can also be inaccurate; they are a
cross-check, not proof of a station's location.

Source: opendatasicilia/comuni-italiani `main.csv`, derived from ISTAT.
Runtime fetch + local cache; no redistribution."""

from __future__ import annotations

import csv
import io
import math
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .cache import write_atomic
from .validation import QueryError, parse_near, validate_download

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


# Common bilingual name mappings for major Italian cities and South Tyrol.
# MIMIT uses the Italian name but users/agents may use English, French, or
# German forms. Keyed by normalized uppercase foreign name. Each entry appears
# once — words shared across languages (e.g. ROME = English + French) are
# listed once and treated as language-neutral.
BILINGUAL_MAP = {
    # South Tyrol / Südtirol (German → Italian)
    "BOZEN": "BOLZANO",
    "MERAN": "MERANO",
    "BRIXEN": "BRESSANONE",
    "BRUNECK": "BRUNICO",
    "STERZING": "VIPITENO",
    "LEIFERS": "LAIVES",
    "KALTERN": "CALDARO SULLA STRADA DEL VINO",
    "EPPAN": "APPIANO SULLA STRADA DEL VINO",
    "NEUMARKT": "EGNA",
    "ST. ULRICH": "ORTISEI",
    "ST. CHRISTINA": "SANTA CRISTINA VALGARDENA",
    "WOLKENSTEIN": "SELVA DI VAL GARDENA",
    "SCHLANDERS": "SILANDRO",
    "MALS": "MALLES VENOSTA",
    "KLAUSEN": "CHIUSA",
    "NATURNS": "NATURNO",
    "LATSCH": "LACES",
    "AUER": "ORA",
    "PRAD": "PRATO ALLO STELVIO",
    # Major Italian cities — German forms
    "ROM": "ROMA",
    "MAILAND": "MILANO",
    "VENEDIG": "VENEZIA",
    "FLORENZ": "FIRENZE",
    "NEAPEL": "NAPOLI",
    "GENUA": "GENOVA",
    "SYRAKUS": "SIRACUSA",
    # Major Italian cities — English forms
    "ROME": "ROMA",
    "MILAN": "MILANO",
    "VENICE": "VENEZIA",
    "FLORENCE": "FIRENZE",
    "TURIN": "TORINO",
    "NAPLES": "NAPOLI",
    "GENOA": "GENOVA",
    "PADUA": "PADOVA",
    "SYRACUSE": "SIRACUSA",
    "MANTUA": "MANTOVA",
    # Major Italian cities — French forms (only the ones that differ from above)
    "VENISE": "VENEZIA",
    "GENES": "GENOVA",
    "PADOUE": "PADOVA",
    "MANTOUE": "MANTOVA",
}


def normalize_comune(name: str) -> str:
    """Uppercase, trim, collapse internal whitespace. MIMIT uses uppercase
    names; opendatasicilia uses capitalized — uppercase makes both match."""
    if not name:
        return ""
    n = " ".join(name.strip().upper().split())
    # Resolve common German names to the Italian names used in MIMIT/ISTAT.
    return BILINGUAL_MAP.get(n, n)


def _cached_path(refresh: bool, max_age: int, timeout: int) -> Path | None:
    validate_download(timeout, max_age)
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
    if not _read_municipalities(data.decode("utf-8-sig")):
        if path.exists():
            print("pitstop: invalid municipality reference; using the cached copy", file=sys.stderr)
            return path
        raise OSError("municipality reference contained no usable records")
    write_atomic(path, data)
    return path


def load_comune_coords(
    *,
    refresh: bool = False,
    max_age: int = DEFAULT_COMUNI_MAX_AGE,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Coordinates keyed by (name, province), plus unambiguous names.

    Empty on fetch failure with no cache. These reference coordinates are only
    for station sanity checks; charger searches use the mapped OSM center.
    """
    path = _cached_path(refresh, max_age, timeout)
    if path is None:
        return {}
    return _parse_comuni(path)


@dataclass(frozen=True)
class Municipality:
    name: str
    province: str
    istat_id: str
    lat: float
    lon: float

    def to_dict(self) -> dict:
        return {"comune": self.name, "provincia": self.province, "comune_id": self.istat_id}


def _read_municipalities(text: str) -> list[Municipality]:
    records = []
    for row in csv.DictReader(io.StringIO(text)):
        name = normalize_comune(row.get("comune", ""))
        code = (row.get("pro_com_t") or "").strip()
        province = (row.get("sigla") or "").strip().upper()
        if not name or not code.isdigit() or len(code) != 6 or not province:
            continue
        try:
            lat, lon = float(row["lat"]), float(row["long"])
        except (KeyError, ValueError, TypeError):
            continue
        if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            records.append(Municipality(name, province, code, lat, lon))
    return records


def _parse_comuni(path: Path) -> dict:
    out = {}
    by_name: dict[str, list[Municipality]] = {}
    for place in _read_municipalities(path.read_text(encoding="utf-8-sig")):
        out[(place.name, place.province)] = (place.lat, place.lon)
        by_name.setdefault(place.name, []).append(place)
    for name, places in by_name.items():
        if len(places) == 1:
            out[name] = (places[0].lat, places[0].lon)
    return out


def find_municipalities(query: str = "", provincia: str = "", *,
                        refresh: bool = False, timeout: int = 60) -> list[Municipality]:
    path = _cached_path(refresh, DEFAULT_COMUNI_MAX_AGE, timeout)
    if path is None:
        raise OSError("municipality reference unavailable; use explicit --near coordinates")
    records = _read_municipalities(path.read_text(encoding="utf-8-sig"))
    if not records:
        raise OSError("municipality reference contained no usable records; retry with --refresh or use --near")
    query = normalize_comune(query)
    province = provincia.strip().upper()
    return sorted((p for p in records if (not query or query in p.name or query == p.istat_id)
                   and (not province or p.province == province)), key=lambda p: (p.name, p.province))


def resolve_municipality(comune: str = "", provincia: str = "", comune_id: str = "", *,
                         refresh: bool = False, timeout: int = 60) -> dict:
    from . import overpass
    from .core import haversine_km

    name = normalize_comune(comune)
    code = comune_id.strip()
    if code and (not code.isdigit() or len(code) != 6):
        raise QueryError("comune_id must be a six-digit ISTAT municipality code")
    candidates = [p for p in find_municipalities(code or name, provincia, refresh=refresh, timeout=timeout)
                  if (not code or p.istat_id == code) and (not name or p.name == name)]
    if not candidates:
        raise QueryError(f"municipality {comune or comune_id!r} not found; use pitstop places or --near")
    if len(candidates) != 1:
        choices = ", ".join(f"{p.name} ({p.province}, {p.istat_id})" for p in candidates)
        raise QueryError(f"ambiguous municipality: {choices}; select --provincia or --comune-id")
    place = candidates[0]
    query = ('[out:json][timeout:25];rel["boundary"="administrative"]'
             f'["admin_level"="8"]["ref:ISTAT"="{place.istat_id}"];'
             '(._;node(r:"admin_centre"););out body;')
    freshness: dict = {}
    elements, error = overpass.fetch_elements(query, refresh=refresh, timeout=timeout,
                                              metadata=freshness)
    relations = [e for e in elements if e.get("type") == "relation"
                 and e.get("tags", {}).get("ref:ISTAT") == place.istat_id]
    center_ids = {m.get("ref") for r in relations for m in r.get("members", [])
                  if m.get("role") == "admin_centre" and m.get("type") == "node"}
    centers = [e for e in elements if e.get("type") == "node" and e.get("id") in center_ids]
    if len(relations) != 1 or len(centers) != 1:
        raise OSError(f"no unique mapped center for {place.name} ({place.province}); "
                      f"use --near with known coordinates" + (f": {error}" if error else ""))
    center = centers[0]
    lat, lon = parse_near(f"{center.get('lat')},{center.get('lon')}")
    distance = round(haversine_km(place.lat, place.lon, lat, lon), 2)
    warnings = [error] if error else []
    if distance > 5:
        warnings.append(f"reference coordinate differs by {distance:g} km; using the linked OSM administrative center")
    return {**place.to_dict(), "lat": lat, "lon": lon,
            "source": overpass.SOURCE_NAME,
            "source_url": f"https://www.openstreetmap.org/node/{center['id']}",
            "identity_source": COMUNI_SOURCE_NAME,
            "reference_distance_km": distance, "freshness": freshness, "warnings": warnings}


def resolve_search_location(near: str, comune: str = "", provincia: str = "", comune_id: str = "", *,
                            refresh: bool = False, timeout: int = 60) -> tuple[tuple[float, float], dict | None]:
    if near.strip():
        if comune.strip() or provincia.strip() or comune_id.strip():
            raise QueryError("pass either near coordinates or a municipality selector")
        return parse_near(near), None
    if not comune.strip() and not comune_id.strip():
        raise QueryError("pass --near, --comune, or --comune-id")
    location = resolve_municipality(comune, provincia, comune_id, refresh=refresh, timeout=timeout)
    return (location["lat"], location["lon"]), location
