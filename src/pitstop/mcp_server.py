"""MCP server exposing pitstop's Italian fuel-price data as agent tools.

Thin wrapper over pitstop.core (the same logic the CLI uses). Requires the
optional `mcp` extra: pip install "pitstop[mcp]". Run with `pitstop-mcp`."""

from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import core

mcp = FastMCP("pitstop")

_CAVEATS = (
    " Data is daily (not real-time): prices are as of ~08:00 the day before "
    "price_extraction_date. Italy only. `fuel` is a substring match, so 'Gasolio' "
    "also matches variants like 'Gasolio Alpino'. Some operators report placeholder "
    "prices (e.g. 1.000); set min_price (e.g. 1.2) to skip them when ranking."
)

_FIND_STATIONS_DESC = (
    "Find Italian fuel stations and their prices from MIMIT open data. Filter by "
    "comune (municipality), provincia (2-letter, e.g. BZ), brand, fuel (substring, "
    'case-insensitive), near ("lat,lon") within radius_km, and service mode '
    "(self_only/served_only). Set cheapest=True to sort by ascending price, and "
    "min_price to drop placeholder values. Returns a JSON envelope with provenance "
    "and a stations list." + _CAVEATS
)

_FIND_CHEAPEST_DESC = (
    "Find the cheapest Italian stations for a given fuel, near a coordinate "
    '("lat,lon") or in a comune. By default applies a fuel-aware price floor '
    "(skips placeholder values for petrol/diesel, no floor for cheap fuels like "
    "GPL); pass min_price >= 0 to override. Returns a provenance-carrying JSON "
    "envelope sorted cheapest-first." + _CAVEATS
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
    limit: int = 20,
) -> dict:
    ds = core.load()
    stations = core.query_stations(
        ds,
        comune=comune,
        provincia=provincia,
        brand=brand,
        near=_parse_near(near),
        radius_km=radius_km,
        fuel=fuel,
        self_only=self_only,
        served_only=served_only,
        cheapest=cheapest,
        min_price=min_price,
        limit=limit,
    )
    query = {
        k: v
        for k, v in {
            "fuel": fuel,
            "comune": comune,
            "provincia": provincia,
            "brand": brand,
            "near": near,
            "radius_km": radius_km if near.strip() else None,
            "self": self_only or None,
            "served": served_only or None,
            "cheapest": cheapest or None,
            "min_price": min_price or None,
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
    limit: int = 5,
) -> dict:
    if min_price < 0:
        min_price = core.default_floor(fuel)
    ds = core.load()
    stations = core.query_stations(
        ds,
        comune=comune,
        near=_parse_near(near),
        radius_km=radius_km,
        fuel=fuel,
        self_only=self_only,
        cheapest=True,
        min_price=min_price,
        limit=limit,
    )
    query: dict = {"fuel": fuel, "cheapest": True, "min_price": min_price}
    if comune:
        query["comune"] = comune
    if near.strip():
        query["near"] = near
        query["radius_km"] = radius_km
    if self_only:
        query["self"] = True
    return core.response_envelope(ds, stations, query)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
