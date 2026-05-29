"""Fetch, cache, parse, and join the Italian MIMIT "Osservaprezzi Carburanti"
open data: a station registry (anagrafica) and a daily practiced-price file,
keyed on idImpianto. Standard library only."""

from __future__ import annotations

import csv
import math
import os
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    prices: list[Price], fuel: str = "", self_only: bool = False, served_only: bool = False
) -> list[Price]:
    fuel = fuel.strip().lower()
    out = []
    for p in prices:
        if fuel and fuel not in p.fuel.lower():
            continue
        if self_only and not p.self_service:
            continue
        if served_only and p.self_service:
            continue
        out.append(p)
    return out


def min_price(prices: list[Price]) -> float | None:
    return min((p.price for p in prices), default=None)


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
