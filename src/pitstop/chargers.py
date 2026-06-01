"""EV charging-station discovery via OpenStreetMap's Overpass API.

Italian EV pricing isn't published openly in a usable form yet (the AFIR
National Access Point/DATEX II rollout is still maturing), so this module
focuses on **locations + capability** — operator, plug types, max kW, fee,
access — which is what most "where can I charge near X" questions need."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import overpass
from .core import haversine_km, in_italy, now_iso

# Map OSM `socket:<key>` to a human-readable plug name.
_SOCKET_TYPES = {
    "type2": "Type 2 (AC)",
    "type2_combo": "CCS Type 2",
    "type2_cable": "Type 2 (AC, tethered)",
    "type1": "Type 1 (AC)",
    "type1_combo": "CCS Type 1",
    "chademo": "CHAdeMO",
    "schuko": "Schuko (domestic)",
    "tesla_supercharger": "Tesla Supercharger",
    "tesla_destination": "Tesla Destination",
    "tesla_supercharger_ccs": "Tesla Supercharger (CCS)",
    "tesla_standard": "Tesla",
}

_DC_FAST_TYPES = {"type2_combo", "type1_combo", "chademo",
                  "tesla_supercharger", "tesla_supercharger_ccs"}


@dataclass
class Socket:
    type: str  # human-readable
    count: int = 1
    max_power_kw: float | None = None
    osm_key: str = ""

    def to_dict(self) -> dict:
        d = {"type": self.type, "count": self.count}
        if self.max_power_kw is not None:
            d["max_power_kw"] = self.max_power_kw
        return d


@dataclass
class EvStation:
    osm_id: int
    name: str
    operator: str
    lat: float
    lon: float
    capacity: int | None
    sockets: list[Socket] = field(default_factory=list)
    max_power_kw: float | None = None
    fee: bool | None = None
    access: str = ""
    opening_hours: str = ""
    distance_km: float | None = None

    def to_dict(self) -> dict:
        d = {
            "osm_id": self.osm_id,
            "name": self.name,
            "operator": self.operator,
            "lat": self.lat,
            "lon": self.lon,
            "sockets": [s.to_dict() for s in self.sockets],
        }
        if self.capacity is not None:
            d["capacity"] = self.capacity
        if self.max_power_kw is not None:
            d["max_power_kw"] = self.max_power_kw
        if self.fee is not None:
            d["fee"] = self.fee
        if self.access:
            d["access"] = self.access
        if self.opening_hours:
            d["opening_hours"] = self.opening_hours
        if self.distance_km is not None:
            d["distance_km"] = self.distance_km
        return d


def _parse_kw(raw: str | None) -> float | None:
    """Pull a kW number out of OSM strings like '22 kW', '50kW', '22000 W', '22'."""
    if not raw:
        return None
    s = str(raw).strip().lower().replace(",", ".")
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(kw|w)?", s)
    if not m:
        return None
    val = float(m.group(1))
    unit = (m.group(2) or "kw").lower()
    if unit == "w":
        val /= 1000.0
    return round(val, 1)


def _parse_yes_no(raw: str | None) -> bool | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("yes", "true", "1"):
        return True
    if s in ("no", "false", "0"):
        return False
    return None


def parse_element(el: dict) -> EvStation | None:
    """Parse one OSM node/way element with `tags` into an EvStation."""
    tags = el.get("tags") or {}
    if tags.get("amenity") != "charging_station":
        return None
    lat = el.get("lat")
    lon = el.get("lon")
    # ways have center.lat/lon via Overpass `out center`
    if lat is None or lon is None:
        center = el.get("center") or {}
        lat, lon = center.get("lat"), center.get("lon")
    if lat is None or lon is None:
        return None

    sockets: list[Socket] = []
    for k, v in tags.items():
        # match keys like socket:type2 (count) — ignore the :output / :voltage variants
        if not k.startswith("socket:") or k.count(":") != 1:
            continue
        subkey = k.split(":", 1)[1]
        try:
            count = int(str(v).strip())
        except (TypeError, ValueError):
            count = 1
        power = _parse_kw(tags.get(f"{k}:output") or tags.get(f"{k}:max_power"))
        sockets.append(Socket(
            type=_SOCKET_TYPES.get(subkey, subkey.replace("_", " ").title()),
            count=count,
            max_power_kw=power,
            osm_key=subkey,
        ))

    max_kw = max((s.max_power_kw for s in sockets if s.max_power_kw is not None), default=None)
    try:
        capacity = int(tags["capacity"]) if "capacity" in tags else None
    except (TypeError, ValueError):
        capacity = None

    return EvStation(
        osm_id=el.get("id", 0),
        name=tags.get("name", "").strip(),
        operator=tags.get("operator", "").strip(),
        lat=float(lat),
        lon=float(lon),
        capacity=capacity,
        sockets=sockets,
        max_power_kw=max_kw,
        fee=_parse_yes_no(tags.get("fee")),
        access=tags.get("access", "").strip(),
        opening_hours=tags.get("opening_hours", "").strip(),
    )


def _overpass_query(lat: float, lon: float, radius_m: int) -> str:
    return (
        "[out:json][timeout:25];\n"
        f"( node[\"amenity\"=\"charging_station\"](around:{radius_m},{lat},{lon});\n"
        f"  way[\"amenity\"=\"charging_station\"](around:{radius_m},{lat},{lon}); );\n"
        "out body center;"
    )


def find_chargers(
    *,
    near: tuple[float, float],
    radius_km: float = 10.0,
    operator: str = "",
    socket: str = "",
    min_power_kw: float = 0.0,
    free_only: bool = False,
    public_only: bool = False,
    refresh: bool = False,
) -> list[EvStation]:
    """Fetch and filter EV charging stations from OSM around a point."""
    if not in_italy(near[0], near[1]):
        # Allow queries anywhere — pitstop's Italy bbox is for the fuel data; for
        # OSM EV the user can query elsewhere if they want. Just don't bail.
        pass
    radius_m = int(max(100, radius_km * 1000))
    elements = overpass.fetch_elements(_overpass_query(near[0], near[1], radius_m),
                                        refresh=refresh)

    out: list[EvStation] = []
    op_lc = operator.strip().lower()
    sock_lc = socket.strip().lower()
    for el in elements:
        st = parse_element(el)
        if st is None:
            continue
        if op_lc and op_lc not in st.operator.lower():
            continue
        if sock_lc and not any(sock_lc in (s.type.lower() + " " + s.osm_key.lower())
                                for s in st.sockets):
            continue
        if min_power_kw > 0 and (st.max_power_kw is None or st.max_power_kw < min_power_kw):
            continue
        if free_only and st.fee is True:
            continue
        if public_only and st.access and st.access.lower() not in ("public", "yes", "permissive"):
            continue
        st.distance_km = round(haversine_km(near[0], near[1], st.lat, st.lon), 2)
        out.append(st)

    out.sort(key=lambda s: s.distance_km if s.distance_km is not None else math.inf)
    return out


def response_envelope(stations: list[EvStation], query: dict) -> dict:
    return {
        "source": overpass.SOURCE_NAME,
        "source_url": overpass.SOURCE_URL,
        "generated_at": now_iso(),
        "query": query,
        "count": len(stations),
        "stations": [s.to_dict() for s in stations],
        "disclaimer": (
            "Unofficial tool. EV-charger data from OpenStreetMap via Overpass API "
            "(© OpenStreetMap contributors, ODbL). Coverage and freshness vary. "
            "Power, plug types, and access fields reflect what mappers entered — "
            "verify on-site or via the operator before relying on them."
        ),
    }
