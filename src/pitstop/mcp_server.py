"""MCP server exposing pitstop's Italian fuel-price data as agent tools.

Thin wrapper over pitstop.core (the same logic the CLI uses). Requires the
optional `mcp` extra: pip install "pitstop-cli[mcp]". Run with `pitstop-mcp`."""

from typing import Any, Optional

try:  # mcp 2.x renamed FastMCP to MCPServer and moved ToolAnnotations out of mcp.types
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp_types import ToolAnnotations
    _ANNOTATIONS_KW = {"read_only_hint": True, "destructive_hint": False,
                       "idempotent_hint": True, "open_world_hint": True}
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.types import ToolAnnotations
    _ANNOTATIONS_KW = {"readOnlyHint": True, "destructiveHint": False,
                       "idempotentHint": True, "openWorldHint": True}

from . import chargers as ev_chargers
from . import core, geocoding, validation

mcp = _Server("pitstop")
_READ_ONLY = ToolAnnotations(**_ANNOTATIONS_KW)

_CAVEATS = (
    " Data is daily (not real-time): prices are as of ~08:00 the day before "
    "price_extraction_date. Italy only. `fuel` supports comma-separated values "
    "(e.g. 'Benzina,Gasolio') and is a substring match. `comune` supports "
    "international names (Rome, Mailand, Venise). Some operators report placeholder "
    "prices (e.g. 1.000); set min_price (e.g. 1.2) to skip them when ranking. Every "
    "price carries a `median_basis`: a `screened` price also carries regional_median "
    "and deviation_pct, plus `outlier: true` when it is >15% below the fuel's median "
    "in that provincia OR below the Tukey lower fence Q1-1.5*IQR. The `outlier` key "
    "is present only when it is true, so read it as optional; `median_basis` is what "
    "tells you whether the check ran at all. Use the flag to caveat, or set "
    "max_deviation_pct to silently drop suspect prices. An `unscreened` price sits in "
    "a (fuel, provincia) bucket with too few samples for a median, so no outlier "
    "check ran on it — do not present it as verified. The envelope's `quality` block "
    "counts screened vs unscreened prices for the current answer."
    " `coverage` separates fetched stations, matches before the limit, and returned "
    "stations. `freshness` reports local download times, not price-update times."
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
    return validation.parse_near(near)


@mcp.tool(annotations=_READ_ONLY, structured_output=True)
def list_fuels() -> dict[str, Any]:
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


@mcp.tool(annotations=_READ_ONLY, structured_output=True)
def get_stats(fuel: str = "") -> dict[str, Any]:
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


@mcp.tool(description=_FIND_STATIONS_DESC, annotations=_READ_ONLY, structured_output=True)
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
) -> dict[str, Any]:
    near_coords = _parse_near(near)
    validation.validate_search(near_coords, radius_km, limit)
    validation.validate_nonnegative(min_price=min_price, max_age_days=max_age_days,
                                    max_deviation_pct=max_deviation_pct)
    ds = core.load()
    comune_norm = geocoding.normalize_comune(comune)
    stations = core.query_stations(
        ds,
        comune=comune_norm,
        provincia=provincia,
        brand=brand,
        near=near_coords,
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
            "max_deviation_pct": max_deviation_pct or None,
            "drop_outliers": drop_outliers or None,
            "limit": limit,
        }.items()
        if v not in ("", None, False)
    }
    return core.response_envelope(ds, stations, query)


@mcp.tool(description=_FIND_CHEAPEST_DESC, annotations=_READ_ONLY, structured_output=True)
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
) -> dict[str, Any]:
    near_coords = _parse_near(near)
    validation.validate_search(near_coords, radius_km, limit)
    if min_price == -1:
        min_price = core.default_floor(fuel)
    if max_age_days == -1:
        max_age_days = 90  # ignore stale records when ranking by price
    validation.validate_nonnegative(min_price=min_price, max_age_days=max_age_days,
                                    max_deviation_pct=max_deviation_pct)
    ds = core.load()
    comune_norm = geocoding.normalize_comune(comune)
    stations = core.query_stations(
        ds,
        comune=comune_norm,
        near=near_coords,
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
    "municipality name) or `comune_id` (six-digit ISTAT ID from find_places). "
    "For duplicate names, specify provincia. Municipality IDs resolve to mapped "
    "OpenStreetMap administrative centers; location records the center and warnings. "
    "Surface location warnings, fetch errors, coverage, and cache freshness. Filter by "
    "operator substring, plug type (e.g. 'ccs', 'chademo', 'type2'), minimum "
    "max-power kW, free-only, and public-access-only. Returns a JSON envelope "
    "with operator, plug types, max kW, fee, access, distance, and (when the "
    "operator is recognized) a `tariff_info_url` pointing to the operator's "
    "official tariff page. **Per-station €/kWh tariffs are never returned by this "
    "tool**: it parses OpenStreetMap's `fee` yes/no flag and no price field. When a "
    "user asks about price, surface the `tariff_info_url` for the relevant "
    "operator(s) rather than guessing a price."
)


@mcp.tool(description=_FIND_CHARGERS_DESC, annotations=_READ_ONLY, structured_output=True)
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
    provincia: str = "",
    comune_id: str = "",
) -> dict[str, Any]:
    near_coords = _parse_near(near)
    validation.validate_search(near_coords, radius_km, limit)
    validation.validate_nonnegative(min_power_kw=min_power_kw)
    (lat, lon), location = geocoding.resolve_search_location(near, comune, provincia, comune_id)

    stations, error = ev_chargers.find_chargers(
        near=(lat, lon), radius_km=radius_km, operator=operator, socket=socket,
        min_power_kw=min_power_kw, free_only=free_only, public_only=public_only, limit=limit,
    )
    query = {"near": f"{lat},{lon}", "radius_km": radius_km}
    if comune:
        query["comune"] = comune
    if provincia:
        query["provincia"] = provincia
    if comune_id:
        query["comune_id"] = comune_id
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
    return ev_chargers.response_envelope(stations, query, error=error, location=location)


@mcp.tool(annotations=_READ_ONLY, structured_output=True)
def find_places(query: str, provincia: str = "", limit: int = 20) -> dict[str, Any]:
    """Find Italian municipality names, province codes, and six-digit ISTAT IDs.
    Use before a charger search when a municipality name is ambiguous; pass the
    chosen comune_id or provincia to find_chargers. Supports names such as Bozen.
    """
    validation.validate_search(None, 1, limit)
    places = geocoding.find_municipalities(query, provincia)
    matched = len(places)
    if limit:
        places = places[:limit]
    return {"source": geocoding.COMUNI_SOURCE_NAME, "source_url": geocoding.COMUNI_URL,
            "query": query, "count": len(places), "matched_count": matched,
            "truncated": len(places) < matched, "places": [p.to_dict() for p in places]}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
