"""MCP server exposing pitstop's Italian fuel-price data as agent tools.

Thin wrapper over pitstop.core (the same logic the CLI uses). Requires the
optional `mcp` extra: pip install "pitstop[mcp]". Run with `pitstop-mcp`."""

from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import chargers as ev_chargers
from . import core, geocoding

mcp = FastMCP("pitstop")

_CAVEATS = (
    " Data is daily (not real-time): prices are as of ~08:00 the day before "
    "price_extraction_date. Italy only. `fuel` supports comma-separated values "
    "(e.g. 'Benzina,Gasolio') and is a substring match. `comune` supports "
    "international names (Rome, Mailand, Venise). Some operators report placeholder "
    "prices (e.g. 1.000); set min_price (e.g. 1.2) to skip them when ranking. Every "
    "price carries a `median_basis`: a `screened` price also carries regional_median "
    "and deviation_pct, plus `outlier: true` when it is >15% below the fuel's median "
    "in that provincia OR below the Tukey lower fence Q1-1.5*IQR. The `outlier` key "
    "is present only when it is true, so read it as optional — its absence means "
    "'not flagged', and `median_basis` is what tells you whether the check ran at "
    "all. Use the flag to caveat, or set max_deviation_pct to silently drop suspect "
    "prices. An `unscreened` price sits in a (fuel, provincia) bucket with too few "
    "samples for a median, so no "
    "outlier check ran on it — do not present it as verified. The envelope's `quality` "
    "block counts screened vs unscreened prices for the current answer."
)

_FIND_STATIONS_DESC = (
    "Find Italian fuel stations and their prices from MIMIT open data. Filter by "
    "comune (municipality; supports international names like Rome/Milan/Bozen), "
    "provincia (2-letter, e.g. BZ), brand, fuel (substring, case-insensitive; "
    'supports comma-separated lists), near ("lat,lon") within radius_km, and '
    "service mode (self_only/served_only). Set cheapest=True to sort by ascending "
    "price, and min_price to drop placeholder values. Returns a JSON envelope with "
    "provenance, navigation URLs, and a stations list." + _CAVEATS
)

_FIND_CHEAPEST_DESC = (
    "Find the cheapest Italian stations for a given fuel, near a coordinate "
    '("lat,lon") or in a comune (supports international names). By default '
    "applies a fuel-aware price floor (skips placeholder values for petrol/diesel, "
    "no floor for cheap fuels like GPL), ignores prices not updated in the last "
    "90 days, and drops statistical outliers (>15% below median OR below the "
    "Tukey lower fence). Override via min_price, max_age_days, drop_outliers. "
    "Returns a provenance-carrying JSON envelope sorted cheapest-first with "
    "navigation URLs." + _CAVEATS
)


def _parse_near(near: str) -> Optional[tuple]:
    if not near.strip():
        return None
    lat, lon = near.split(",")
    return (float(lat.strip()), float(lon.strip()))


@mcp.tool()
def list_fuels() -> dict:
    """List the fuel-type names in the Italian MIMIT fuel dataset, with the number
    of price rows for each. Call this first to discover exact `fuel` values."""
    ds = core.load()
    counts: dict[str, int] = {}
    for st in ds.stations.values():
        for p in st.prices:
            counts[p.fuel] = counts.get(p.fuel, 0) + 1
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "source": core.SOURCE_NAME,
        "price_extraction_date": ds.price_date,
        "fuels": [{"fuel": f, "count": c} for f, c in items],
    }


@mcp.tool()
def get_stats(fuel: str = "") -> dict:
    """Get macro-level price statistics (median, min, max) per Italian province
    and a national aggregate. Use this to give advice on whether a region is
    generally cheaper or more expensive than others. `fuel` supports
    comma-separated values."""
    ds = core.load()
    stats = core.fuel_stats(ds, fuel=fuel)
    return {
        "source": core.SOURCE_NAME,
        "price_extraction_date": ds.price_date,
        "generated_at": core.now_iso(),
        "stats": stats
    }


@mcp.tool(description=_FIND_STATIONS_DESC)
def find_stations(
    fuel: str = "",
    comune: str = "",
    provincia: str = "",
    brand: str = "",
    near: str = "",
    radius_km: float = 10.0,
    self_only: bool = False,
    served_only: bool = False,
    cheapest: bool = False,
    min_price: float = 0.0,
    max_age_days: int = 0,
    max_deviation_pct: float = 0.0,
    drop_outliers: bool = False,
    limit: int = 20,
) -> dict:
    ds = core.load()
    comune_norm = geocoding.normalize_comune(comune)
    stations = core.query_stations(
        ds,
        comune=comune_norm,
        provincia=provincia,
        brand=brand,
        near=_parse_near(near),
        radius_km=radius_km,
        fuel=fuel,
        self_only=self_only,
        served_only=served_only,
        cheapest=cheapest,
        min_price=min_price,
        max_age_days=max_age_days,
        max_deviation_pct=max_deviation_pct,
        drop_outliers=drop_outliers,
        limit=limit,
    )
    query = {
        k: v
        for k, v in {
            "fuel": fuel,
            "comune": comune_norm or None,
            "provincia": provincia,
            "brand": brand,
            "near": near,
            "radius_km": radius_km if near.strip() else None,
            "self": self_only or None,
            "served": served_only or None,
            "cheapest": cheapest or None,
            "min_price": min_price or None,
            "fresh_within_days": max_age_days or None,
        }.items()
        if v not in ("", None, False)
    }
    return core.response_envelope(ds, stations, query)


@mcp.tool(description=_FIND_CHEAPEST_DESC)
def find_cheapest(
    fuel: str,
    comune: str = "",
    near: str = "",
    radius_km: float = 10.0,
    self_only: bool = False,
    min_price: float = -1.0,
    max_age_days: int = -1,
    max_deviation_pct: float = 0.0,
    drop_outliers: bool = True,
    limit: int = 5,
) -> dict:
    if min_price < 0:
        min_price = core.default_floor(fuel)
    if max_age_days < 0:
        max_age_days = 90  # ignore stale records when ranking by price
    ds = core.load()
    comune_norm = geocoding.normalize_comune(comune)
    stations = core.query_stations(
        ds,
        comune=comune_norm,
        near=_parse_near(near),
        radius_km=radius_km,
        fuel=fuel,
        self_only=self_only,
        cheapest=True,
        min_price=min_price,
        max_age_days=max_age_days,
        max_deviation_pct=max_deviation_pct,
        drop_outliers=drop_outliers,
        limit=limit,
    )
    query: dict = {
        "fuel": fuel,
        "cheapest": True,
        "min_price": min_price,
        "fresh_within_days": max_age_days,
        "drop_outliers": drop_outliers,
    }
    if comune_norm:
        query["comune"] = comune_norm
    if near.strip():
        query["near"] = near
        query["radius_km"] = radius_km
    if self_only:
        query["self"] = True
    return core.response_envelope(ds, stations, query)


_FIND_CHARGERS_DESC = (
    "Find EV charging stations near a coordinate or Italian comune, from "
    "OpenStreetMap. Pass either `near` (\"lat,lon\") or `comune` (Italian "
    "municipality name; resolved via the comune-coords reference). Filter by "
    "operator substring, plug type (e.g. 'ccs', 'chademo', 'type2'), minimum "
    "max-power kW, free-only, and public-access-only. Returns a JSON envelope "
    "with operator, plug types, max kW, fee, access, distance, and (when the "
    "operator is recognized) a `tariff_info_url` pointing to the operator's "
    "official tariff page. **Per-station €/kWh tariffs are not in this dataset** "
    "— as of mid-2026 they are not openly machine-readable in Italy (AFIR DATEX "
    "II is upload-only; Chargeprice/Eco-Movement are paid). When a user asks "
    "about price, surface the `tariff_info_url` for the relevant operator(s) "
    "rather than guessing a price."
)


@mcp.tool(description=_FIND_CHARGERS_DESC)
def find_chargers(
    near: str = "",
    comune: str = "",
    radius_km: float = 10.0,
    operator: str = "",
    socket: str = "",
    min_power_kw: float = 0.0,
    free_only: bool = False,
    public_only: bool = False,
    limit: int = 20,
) -> dict:
    if not near.strip() and not comune.strip():
        return ev_chargers.response_envelope([], {}, error="pass either near or comune")
    if near.strip():
        lat_s, lon_s = near.split(",")
        lat, lon = float(lat_s.strip()), float(lon_s.strip())
    else:
        comune_norm = geocoding.normalize_comune(comune)
        coords = geocoding.load_comune_coords()
        match = coords.get(comune_norm)
        if not match:
            return ev_chargers.response_envelope(
                [], {"comune": comune}, error=f"comune '{comune}' not found"
            )
        lat, lon = match

    stations, error = ev_chargers.find_chargers(
        near=(lat, lon), radius_km=radius_km, operator=operator, socket=socket,
        min_power_kw=min_power_kw, free_only=free_only, public_only=public_only,
    )
    if limit > 0:
        stations = stations[:limit]
    query = {"near": f"{lat},{lon}", "radius_km": radius_km}
    if comune:
        query["comune"] = comune
    if operator:
        query["operator"] = operator
    if socket:
        query["socket"] = socket
    if min_power_kw > 0:
        query["min_power_kw"] = min_power_kw
    if free_only:
        query["free"] = True
    if public_only:
        query["public"] = True
    return ev_chargers.response_envelope(stations, query, error=error)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
