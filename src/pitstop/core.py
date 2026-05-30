"""Fetch, cache, parse, and join the Italian MIMIT "Osservaprezzi Carburanti"
open data: a station registry (anagrafica) and a daily practiced-price file,
keyed on idImpianto. Standard library only."""

from __future__ import annotations

import csv
import math
import os
import statistics
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

ANAGRAFICA_URL = "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
PREZZO_URL = "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"

SOURCE_NAME = "MIMIT Osservaprezzi Carburanti (open data)"
SOURCE_URL = (
    "https://www.mimit.gov.it/it/open-data/elenco-dataset/"
    "carburanti-prezzi-praticati-e-anagrafica-degli-impianti"
)

DISCLAIMER = (
    "Unofficial tool. Source: MIMIT Osservaprezzi Carburanti open data. "
    "Prices are values reported by operators as of ~08:00 the day before the "
    "price extraction date; they are not real-time."
)

DEFAULT_MAX_AGE = 24 * 60 * 60  # seconds
DEFAULT_TIMEOUT = 180  # seconds


@dataclass
class Price:
    fuel: str
    price: float
    self_service: bool
    updated: str

    def to_dict(self) -> dict:
        return {
            "fuel": self.fuel,
            "price": self.price,
            "self_service": self.self_service,
            "updated": self.updated,
        }


@dataclass
class Station:
    id: str
    operator: str
    brand: str
    type: str
    name: str
    address: str
    comune: str
    provincia: str
    lat: float
    lon: float
    prices: list[Price] = field(default_factory=list)
    distance_km: float | None = None
    coordinate_suspect: bool = False

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "operator": self.operator,
            "brand": self.brand,
            "type": self.type,
            "name": self.name,
            "address": self.address,
            "comune": self.comune,
            "provincia": self.provincia,
            "lat": self.lat,
            "lon": self.lon,
            "prices": [p.to_dict() for p in self.prices],
        }
        if self.distance_km is not None:
            d["distance_km"] = self.distance_km
        if self.coordinate_suspect:
            d["coordinate_suspect"] = True
        return d


@dataclass
class Dataset:
    stations: dict[str, Station]
    registry_date: str
    price_date: str


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    d = Path(base) / "pitstop"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cached_file(
    url: str, name: str, *, refresh: bool, max_age: int, timeout: int
) -> Path:
    """Return a local path to the CSV, downloading when missing, stale, or forced."""
    path = cache_dir() / name
    if not refresh and path.exists():
        age = time.time() - path.stat().st_mtime
        if max_age <= 0 or age < max_age:
            return path

    tmp = path.with_suffix(path.suffix + ".tmp")
    req = urllib.request.Request(url, headers={"User-Agent": "pitstop"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    tmp.write_bytes(data)
    tmp.replace(path)  # atomic; a partial download never clobbers a good cache file
    return path


def _read_rows(path: Path) -> tuple[str, list[list[str]]]:
    """Parse a MIMIT pipe-delimited file. Returns (extraction_date, data_rows).

    Line 0 is "Estrazione del YYYY-MM-DD", line 1 is the header, the rest is data.
    """
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter="|")
        rows = list(reader)
    if len(rows) < 2:
        raise ValueError(f"{path.name} has no data rows")
    extraction = ""
    if rows[0]:
        extraction = rows[0][0].removeprefix("Estrazione del ").strip()
    return extraction, rows[2:]


def _parse_registry(path: Path) -> tuple[dict[str, Station], str]:
    date, rows = _read_rows(path)
    stations: dict[str, Station] = {}
    for row in rows:
        if len(row) < 10:
            continue
        sid = row[0].strip()
        if not sid:
            continue
        stations[sid] = Station(
            id=sid,
            operator=row[1].strip(),
            brand=row[2].strip(),
            type=row[3].strip(),
            name=row[4].strip(),
            address=row[5].strip(),
            comune=row[6].strip(),
            provincia=row[7].strip(),
            lat=_to_float(row[8]),
            lon=_to_float(row[9]),
        )
    return stations, date


def _attach_prices(path: Path, stations: dict[str, Station]) -> str:
    date, rows = _read_rows(path)
    for row in rows:
        if len(row) < 5:
            continue
        st = stations.get(row[0].strip())
        if st is None:
            continue
        price = _to_float(row[2], default=None)
        if price is None:
            continue
        st.prices.append(
            Price(
                fuel=row[1].strip(),
                price=price,
                self_service=row[3].strip() == "1",
                updated=_normalize_ts(row[4].strip()),
            )
        )
    return date


def load(
    *,
    refresh: bool = False,
    max_age: int = DEFAULT_MAX_AGE,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dataset:
    """Fetch (or read from cache) both files and return the joined dataset."""
    ana = _cached_file(
        ANAGRAFICA_URL,
        "anagrafica_impianti_attivi.csv",
        refresh=refresh,
        max_age=max_age,
        timeout=timeout,
    )
    prezzo = _cached_file(
        PREZZO_URL,
        "prezzo_alle_8.csv",
        refresh=refresh,
        max_age=max_age,
        timeout=timeout,
    )
    stations, registry_date = _parse_registry(ana)
    price_date = _attach_prices(prezzo, stations)
    return Dataset(stations=stations, registry_date=registry_date, price_date=price_date)


def filter_prices(
    prices: list[Price],
    fuel: str = "",
    self_only: bool = False,
    served_only: bool = False,
    min_price: float = 0.0,
    max_age_days: int = 0,
    today: date | None = None,
) -> list[Price]:
    fuel = fuel.strip().lower()
    if max_age_days > 0 and today is None:
        today = date.today()
    out = []
    for p in prices:
        if fuel and fuel not in p.fuel.lower():
            continue
        if self_only and not p.self_service:
            continue
        if served_only and p.self_service:
            continue
        if min_price > 0 and p.price < min_price:
            continue
        if max_age_days > 0:
            age = price_age_days(p.updated, today)
            if age is not None and age > max_age_days:
                continue
        out.append(p)
    return out


def price_age_days(updated: str, today: date | None = None) -> int | None:
    """Age of a price in days from its `updated` timestamp. None if unparseable."""
    if today is None:
        today = date.today()
    try:
        d = datetime.fromisoformat(updated).date()
    except ValueError:
        try:
            d = datetime.strptime(updated.split()[0], "%d/%m/%Y").date()
        except (ValueError, IndexError):
            return None
    return (today - d).days


def min_price_of(prices: list[Price]) -> float | None:
    return min((p.price for p in prices), default=None)


def default_floor(fuel: str) -> float:
    """A sensible default min-price floor for ranking, given a fuel name.

    The common placeholder value (1.000) only corrupts cheapest-ranking for
    fuels whose real price is above it (petrol, diesel, methane ~1.3-2.5/kg), so
    those get a 1.2 floor. GPL (LPG, ~0.7-0.9) sits below 1.000, so a 1.2 floor
    would wrongly drop every real price; GPL gets no floor (its 1.000 placeholders
    sink harmlessly to the bottom of an ascending sort)."""
    f = fuel.strip().lower()
    if not f:
        return 0.0
    return 0.0 if "gpl" in f else 1.2


def query_stations(
    ds: Dataset,
    *,
    comune: str = "",
    provincia: str = "",
    brand: str = "",
    near: tuple[float, float] | None = None,
    radius_km: float = 10.0,
    fuel: str = "",
    self_only: bool = False,
    served_only: bool = False,
    cheapest: bool = False,
    min_price: float = 0.0,
    max_age_days: int = 0,
    limit: int = 20,
    validate_comune: bool = True,
    comune_coords: dict[str, tuple[float, float]] | None = None,
) -> list[Station]:
    """Filter, sort, and limit stations. Mutates the dataset's Station objects
    (narrows prices, sets distance_km), so pass a freshly loaded Dataset."""
    today = date.today() if max_age_days > 0 else None
    centroids = comune_centroids(ds)
    if validate_comune and comune_coords is None:
        from . import geocoding
        comune_coords = geocoding.load_comune_coords()
    elif comune_coords is None:
        comune_coords = {}

    out: list[Station] = []
    for st in ds.stations.values():
        if comune and st.comune.casefold() != comune.strip().casefold():
            continue
        if provincia and st.provincia.casefold() != provincia.strip().casefold():
            continue
        if brand and brand.lower() not in st.brand.lower():
            continue

        prices = filter_prices(
            st.prices, fuel, self_only, served_only, min_price, max_age_days, today
        )
        if (fuel or self_only or served_only or min_price > 0 or max_age_days > 0) and not prices:
            continue
        st.prices = prices

        # Flag coordinates that are implausible or far from where they should be.
        # Prefer the true ISTAT-derived comune coord when available (works for
        # single-station comuni); fall back to the in-data comune centroid.
        true_coord = comune_coords.get(st.comune.upper()) if comune_coords else None
        if not in_italy(st.lat, st.lon):
            st.coordinate_suspect = True
        elif true_coord is not None:
            if haversine_km(true_coord[0], true_coord[1], st.lat, st.lon) > SUSPECT_DISTANCE_KM:
                st.coordinate_suspect = True
        else:
            c = centroids.get(st.comune.upper())
            if c is not None and haversine_km(c[0], c[1], st.lat, st.lon) > SUSPECT_DISTANCE_KM:
                st.coordinate_suspect = True

        if near is not None:
            if not in_italy(st.lat, st.lon):
                continue  # invalid coords cannot be reliably near anything
            # Reject stations whose declared comune is geographically too far
            # from the query point — even if the stored coordinate happens to
            # land close (the Rasen case). Tolerance pads for large comuni.
            if true_coord is not None:
                comune_dist = haversine_km(near[0], near[1], true_coord[0], true_coord[1])
                if comune_dist > radius_km + 30.0:
                    continue
            d = haversine_km(near[0], near[1], st.lat, st.lon)
            if d > radius_km:
                continue
            st.distance_km = round(d, 2)
        out.append(st)

    if cheapest:
        out.sort(key=lambda s: (min_price_of(s.prices) is None, min_price_of(s.prices) or 0.0))
    elif near is not None:
        out.sort(key=lambda s: s.distance_km if s.distance_km is not None else float("inf"))
    else:
        out.sort(key=lambda s: (s.comune, s.name))

    if limit > 0:
        out = out[:limit]
    return out


def response_envelope(ds: Dataset, stations: list[Station], query: dict) -> dict:
    """Build the stable JSON response object shared by the CLI and MCP server."""
    return {
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "registry_extraction_date": ds.registry_date,
        "price_extraction_date": ds.price_date,
        "generated_at": now_iso(),
        "query": query,
        "count": len(stations),
        "stations": [s.to_dict() for s in stations],
        "disclaimer": DISCLAIMER,
    }


ITALY_BBOX = (35.0, 47.6, 6.0, 19.0)  # min_lat, max_lat, min_lon, max_lon
SUSPECT_DISTANCE_KM = 30.0


def in_italy(lat: float, lon: float) -> bool:
    """Whether a coordinate sits inside a generous Italy bounding box."""
    return ITALY_BBOX[0] <= lat <= ITALY_BBOX[1] and ITALY_BBOX[2] <= lon <= ITALY_BBOX[3]


def comune_centroids(ds: "Dataset", min_stations: int = 3) -> dict[str, tuple[float, float]]:
    """Median (lat, lon) per comune, only for comuni with at least `min_stations`
    stations. The median resists individual mis-geocoded outliers."""
    groups: dict[str, list[tuple[float, float]]] = {}
    for st in ds.stations.values():
        if not in_italy(st.lat, st.lon):
            continue
        groups.setdefault(st.comune.upper(), []).append((st.lat, st.lon))
    return {
        com: (statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts))
        for com, pts in groups.items()
        if len(pts) >= min_stations
    }


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_float(s: str, default: float | None = 0.0) -> float | None:
    try:
        return float(s.strip().replace(",", "."))
    except (ValueError, AttributeError):
        return default


def _normalize_ts(raw: str) -> str:
    try:
        return datetime.strptime(raw, "%d/%m/%Y %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return raw
