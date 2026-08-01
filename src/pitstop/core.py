"""Fetch, cache, parse, and join the Italian MIMIT "Osservaprezzi Carburanti"
open data: a station registry (anagrafica) and a daily practiced-price file,
keyed on idImpianto. Standard library only."""

from __future__ import annotations

import csv
import math
import os
import statistics
import sys
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
    regional_median: float | None = None
    deviation_pct: float | None = None
    outlier: bool = False
    # "screened" once a (fuel, provincia) median was available to compare against;
    # "unscreened" means no median existed (too few samples), so no outlier check ran.
    median_basis: str = "unscreened"

    def to_dict(self) -> dict:
        d = {
            "fuel": self.fuel,
            "price": self.price,
            "self_service": self.self_service,
            "updated": self.updated,
        }
        if self.regional_median is not None:
            d["regional_median"] = self.regional_median
            d["deviation_pct"] = self.deviation_pct
        # Always emitted: without it an unscreened price is indistinguishable
        # from one that was screened and came out clean (both lack `outlier`).
        d["median_basis"] = self.median_basis
        # Only present when true; absence means "not flagged", and median_basis
        # is what says whether the check ran at all.
        if self.outlier:
            d["outlier"] = True
        return d


def navigation_url(lat: float, lon: float) -> str:
    """Return a Google Maps search URL for the given coordinates."""
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"


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
            "navigation_url": navigation_url(self.lat, self.lon),
            "prices": [p.to_dict() for p in self.prices],
        }
        if self.distance_km is not None:
            d["distance_km"] = self.distance_km
        if self.coordinate_suspect:
            d["coordinate_suspect"] = True
        return d

    def to_geojson_feature(self) -> dict:
        props = self.to_dict()
        lat = props.pop("lat")
        lon = props.pop("lon")
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        }


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

    req = urllib.request.Request(url, headers={"User-Agent": "pitstop"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()

    # MIMIT answers its maintenance page with HTTP 200, so "the request succeeded"
    # is not evidence we were served the CSV. Validate before replacing the cache:
    # otherwise one blip poisons the cache for the whole max_age window.
    if not _looks_like_mimit_csv(data):
        if path.exists():
            print(f"pitstop: {name} download did not look like MIMIT CSV data; "
                  f"keeping the cached copy", file=sys.stderr)
            return path
        raise ValueError(
            f"{name} download did not look like MIMIT CSV data (expected a first line "
            f"'Estrazione del ...'); MIMIT may be serving its maintenance page"
        )

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)  # atomic; a partial download never clobbers a good cache file
    return path


def _looks_like_mimit_csv(data: bytes) -> bool:
    """Whether a downloaded body is a MIMIT extract rather than an error page."""
    head = data[:200].decode("utf-8", errors="replace").lstrip()
    return head.startswith("Estrazione del")


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
    fuels = [f.strip().lower() for f in fuel.split(",") if f.strip()]
    if max_age_days > 0 and today is None:
        today = date.today()
    out = []
    for p in prices:
        if fuels and not any(f in p.fuel.lower() for f in fuels):
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
    max_deviation_pct: float = 0.0,
    drop_outliers: bool = False,
    limit: int = 20,
    validate_comune: bool = True,
    comune_coords: dict[str, tuple[float, float]] | None = None,
) -> list[Station]:
    """Filter, sort, and limit stations. Mutates the dataset's Station objects
    (narrows prices, sets distance_km), so pass a freshly loaded Dataset."""
    today = date.today() if max_age_days > 0 else None
    centroids = comune_centroids(ds)
    stats = fuel_provincia_stats(ds)
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
        # Annotate each surviving price with its (fuel, provincia) market context,
        # then optionally drop prices that fall too far below the local market.
        # outlier flag fires if the price is below EITHER the percentage threshold
        # OR the Tukey lower fence (Q1 - 1.5*IQR) — combining catches both
        # gross misreports in diverse markets and subtle ones in tight markets.
        prov = st.provincia.strip().upper()
        kept_prices: list[Price] = []
        for p in prices:
            s = stats.get((p.fuel.strip().lower(), prov))
            if s is not None:
                med = s["median"]
                p.regional_median = round(med, 3)
                p.deviation_pct = round((p.price - med) / med * 100, 1)
                p.outlier = (p.deviation_pct < -OUTLIER_DEVIATION_PCT
                             or p.price < s["lower_fence"])
                p.median_basis = "screened"
            if max_deviation_pct > 0 and s is not None and p.deviation_pct < -max_deviation_pct:
                continue
            if drop_outliers and p.outlier:
                continue
            kept_prices.append(p)
        active_filter = (fuel or self_only or served_only or min_price > 0
                         or max_age_days > 0 or max_deviation_pct > 0 or drop_outliers)
        if active_filter and not kept_prices:
            continue
        st.prices = kept_prices

        # Flag coordinates that are implausible or far from where they should be.
        # Prefer the data-derived centroid when available (robust if >=3 stations);
        # fall back to the true ISTAT-derived coord (handles single-station comuni).
        c = centroids.get(st.comune.upper())
        true_coord = comune_coords.get(st.comune.upper()) if comune_coords else None

        if not in_italy(st.lat, st.lon):
            st.coordinate_suspect = True
        elif c is not None:
            if haversine_km(c[0], c[1], st.lat, st.lon) > SUSPECT_DISTANCE_KM:
                st.coordinate_suspect = True
        elif true_coord is not None:
            if haversine_km(true_coord[0], true_coord[1], st.lat, st.lon) > SUSPECT_DISTANCE_KM:
                st.coordinate_suspect = True

        if near is not None:
            if not in_italy(st.lat, st.lon):
                continue  # invalid coords cannot be reliably near anything
            # Reject stations whose declared comune is geographically too far
            # from the query point. Prefer centroid, fall back to true_coord.
            ref_comune_coord = c or true_coord
            if ref_comune_coord is not None:
                comune_dist = haversine_km(near[0], near[1], ref_comune_coord[0], ref_comune_coord[1])
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


def price_quality(stations: list[Station]) -> dict:
    """Count how many of the returned prices actually went through the outlier
    check. Thin (fuel, provincia) buckets get no median, so those prices are
    returned unchecked; without this block that gap is invisible."""
    screened = unscreened = outliers = 0
    for st in stations:
        for p in st.prices:
            if p.median_basis == "screened":
                screened += 1
            else:
                unscreened += 1
            if p.outlier:
                outliers += 1
    return {
        "prices": screened + unscreened,
        "screened": screened,
        "unscreened": unscreened,
        "outliers": outliers,
        "note": QUALITY_NOTE,
    }


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
        "quality": price_quality(stations),
        "stations": [s.to_dict() for s in stations],
        "disclaimer": DISCLAIMER,
    }


def geojson_envelope(ds: Dataset, stations: list[Station], query: dict) -> dict:
    """Build a standard GeoJSON FeatureCollection."""
    return {
        "type": "FeatureCollection",
        "metadata": {
            "source": SOURCE_NAME,
            "registry_extraction_date": ds.registry_date,
            "price_extraction_date": ds.price_date,
            "generated_at": now_iso(),
            "query": query,
            "disclaimer": DISCLAIMER,
        },
        "features": [s.to_geojson_feature() for s in stations],
    }


def fuel_stats(ds: Dataset, fuel: str = "") -> dict:
    """Return median, min, max prices per province and region for each fuel."""
    fuels = [f.strip().lower() for f in fuel.split(",") if f.strip()]
    
    # Fuel -> Province/Region -> list[Price]
    prov_bucket: dict[str, dict[str, list[float]]] = {}
    reg_bucket: dict[str, dict[str, list[float]]] = {}
    
    # Mapping of province codes to regions (simplified for core advisory)
    # In a full app we'd use a static lookup, for now we derive from provincia data
    for st in ds.stations.values():
        prov = st.provincia.strip().upper()
        if not prov or len(prov) != 2:
            continue
        for p in st.prices:
            f_key = p.fuel.strip().lower()
            if fuels and not any(f in f_key for f in fuels):
                continue
            prov_bucket.setdefault(p.fuel, {}).setdefault(prov, []).append(p.price)
            # Use provincia as a proxy for region for now, or just focus on prov
            
    out: dict[str, dict] = {}
    for f_name, prov_data in prov_bucket.items():
        f_stats = {"provinces": {}}
        all_prices = []
        for prov, prices in prov_data.items():
            all_prices.extend(prices)
            f_stats["provinces"][prov] = {
                "median": round(statistics.median(prices), 3),
                "min": min(prices),
                "max": max(prices),
                "count": len(prices),
            }
        f_stats["national"] = {
            "median": round(statistics.median(all_prices), 3),
            "min": min(all_prices),
            "max": max(all_prices),
            "count": len(all_prices),
        }
        out[f_name] = f_stats
        
    return out


ITALY_BBOX = (35.0, 47.6, 6.0, 19.0)  # min_lat, max_lat, min_lon, max_lon
SUSPECT_DISTANCE_KM = 30.0
OUTLIER_DEVIATION_PCT = 15.0  # a price more than this far below its (fuel, provincia) median is flagged
MIN_SAMPLES_FOR_MEDIAN = 15

QUALITY_NOTE = (
    "`screened` prices were compared against the median of their (fuel, provincia) "
    f"bucket; `unscreened` prices sit in a bucket with fewer than {MIN_SAMPLES_FOR_MEDIAN} "
    "samples, so no median was computed and no outlier check ran on them — they are "
    "returned as reported. Each price repeats this as `median_basis`."
)


def fuel_provincia_stats(ds: "Dataset", min_n: int = MIN_SAMPLES_FOR_MEDIAN) -> dict[tuple[str, str], dict]:
    """Per (fuel-lowercase, provincia-uppercase) statistics for outlier detection:
    median, Q1, Q3, IQR, and Tukey lower fence (Q1 - 1.5*IQR). Only returned
    where at least `min_n` samples exist. The Tukey fence catches misreports
    in tight markets that a fixed-percentage threshold misses (e.g. a 1.787
    diesel in BZ where the median is 2.099 — only -14.9% but well below the
    1.949 fence)."""
    bucket: dict[tuple[str, str], list[float]] = {}
    for st in ds.stations.values():
        prov = st.provincia.strip().upper()
        if not prov:
            continue
        for p in st.prices:
            fuel = p.fuel.strip().lower()
            if not fuel:
                continue
            bucket.setdefault((fuel, prov), []).append(p.price)
    out: dict[tuple[str, str], dict] = {}
    for key, prices in bucket.items():
        if len(prices) < min_n:
            continue
        q1, _, q3 = statistics.quantiles(prices, n=4)
        iqr = q3 - q1
        out[key] = {
            "median": statistics.median(prices),
            "q1": q1, "q3": q3, "iqr": iqr,
            "lower_fence": q1 - 1.5 * iqr,
        }
    return out


# Back-compat: original median-only helper kept as a thin wrapper.
def fuel_provincia_medians(ds: "Dataset", min_n: int = MIN_SAMPLES_FOR_MEDIAN) -> dict[tuple[str, str], float]:
    return {k: v["median"] for k, v in fuel_provincia_stats(ds, min_n).items()}


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
