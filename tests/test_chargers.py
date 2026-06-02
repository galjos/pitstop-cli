import pytest

from pitstop import chargers


def _node(id_, lat, lon, tags):
    return {"type": "node", "id": id_, "lat": lat, "lon": lon, "tags": tags}


def test_parse_element_extracts_sockets_power_and_meta():
    el = _node(1, 46.49, 11.34, {
        "amenity": "charging_station",
        "operator": "Alperia",
        "name": "Test Hub",
        "capacity": "3",
        "socket:type2_combo": "2",
        "socket:type2_combo:output": "150 kW",
        "socket:chademo": "1",
        "socket:chademo:output": "63 kW",
        "fee": "yes",
        "access": "public",
    })
    st = chargers.parse_element(el)
    assert st is not None
    assert st.operator == "Alperia"
    assert st.capacity == 3
    socks = {s.osm_key: s for s in st.sockets}
    assert socks["type2_combo"].count == 2 and socks["type2_combo"].max_power_kw == 150.0
    assert socks["chademo"].max_power_kw == 63.0
    assert st.max_power_kw == 150.0
    assert st.fee is True
    assert st.access == "public"


def test_parse_element_rejects_non_charging_amenity():
    assert chargers.parse_element(_node(2, 0, 0, {"amenity": "fuel"})) is None


def test_parse_element_handles_watts_and_comma_decimals():
    el = _node(3, 46.5, 11.3, {
        "amenity": "charging_station",
        "socket:type2": "1",
        "socket:type2:output": "22000 W",
        "socket:schuko": "1",
        "socket:schuko:output": "3,7 kW",
    })
    st = chargers.parse_element(el)
    socks = {s.osm_key: s for s in st.sockets}
    assert socks["type2"].max_power_kw == 22.0
    assert socks["schuko"].max_power_kw == 3.7
    assert st.max_power_kw == 22.0


def test_parse_element_unknown_socket_keeps_raw_label():
    el = _node(4, 46.5, 11.3, {
        "amenity": "charging_station",
        "socket:tesla_destination": "4",
    })
    st = chargers.parse_element(el)
    assert st.sockets[0].type == "Tesla Destination"


def test_find_chargers_filters_min_power(monkeypatch):
    """Use the public find_chargers path with an injected Overpass response."""
    elements = [
        _node(10, 46.50, 11.35, {"amenity": "charging_station",
                                 "operator": "X", "socket:type2": "1",
                                 "socket:type2:output": "22 kW"}),
        _node(11, 46.50, 11.35, {"amenity": "charging_station",
                                 "operator": "Y", "socket:type2_combo": "1",
                                 "socket:type2_combo:output": "150 kW"}),
    ]
    monkeypatch.setattr(chargers.overpass, "fetch_elements", lambda *a, **k: (elements, None))
    fast, error = chargers.find_chargers(near=(46.50, 11.35), radius_km=5, min_power_kw=50)
    assert error is None
    assert [s.osm_id for s in fast] == [11]


def test_cpo_tariffs_lookup_matches_substrings_and_prefers_longest():
    from pitstop import cpo_tariffs
    assert cpo_tariffs.lookup("Alperia") and "alperia" in cpo_tariffs.lookup("Alperia").lower()
    assert cpo_tariffs.lookup("Alperia Smart Mobility") == cpo_tariffs.lookup("Alperia")
    # "Enel X Way" must win over "Enel" — longest-key-first lookup.
    enelxway = cpo_tariffs.lookup("Enel X Way")
    enel = cpo_tariffs.lookup("Enel")
    assert enelxway == cpo_tariffs.TARIFF_URLS["enel x way"]
    assert enel == cpo_tariffs.TARIFF_URLS["enel"]
    assert cpo_tariffs.lookup("Some unknown operator") is None
    assert cpo_tariffs.lookup("") is None


def test_find_chargers_attaches_tariff_url(monkeypatch):
    elements = [
        _node(30, 46.50, 11.35, {"amenity": "charging_station", "operator": "Alperia",
                                 "socket:type2": "1"}),
        _node(31, 46.50, 11.35, {"amenity": "charging_station", "operator": "Unknown CPO",
                                 "socket:type2": "1"}),
    ]
    monkeypatch.setattr(chargers.overpass, "fetch_elements", lambda *a, **k: (elements, None))
    out, error = chargers.find_chargers(near=(46.50, 11.35), radius_km=5)
    assert error is None
    by_id = {s.osm_id: s for s in out}
    assert by_id[30].tariff_info_url is not None
    assert "alperia" in by_id[30].tariff_info_url.lower()
    assert by_id[31].tariff_info_url is None


def test_find_chargers_filters_operator(monkeypatch):
    elements = [
        _node(20, 46.50, 11.35, {"amenity": "charging_station", "operator": "Alperia",
                                 "socket:type2": "1"}),
        _node(21, 46.50, 11.35, {"amenity": "charging_station", "operator": "Be Charge",
                                 "socket:type2": "1"}),
    ]
    monkeypatch.setattr(chargers.overpass, "fetch_elements", lambda *a, **k: (elements, None))
    only, error = chargers.find_chargers(near=(46.50, 11.35), radius_km=5, operator="alperia")
    assert error is None
    assert [s.osm_id for s in only] == [20]


# ---- v0.9.0 additions: error envelope, GeoJSON, MCP bilingual normalize ----


def test_response_envelope_carries_error_field():
    env = chargers.response_envelope([], {"comune": "Nowhere"}, error="overpass unreachable")
    assert env["count"] == 0
    assert env["error"] == "overpass unreachable"
    assert "disclaimer" in env  # full shape preserved on error path


def test_geojson_envelope_shape():
    el = _node(50, 46.50, 11.35, {"amenity": "charging_station", "operator": "Alperia",
                                  "socket:type2_combo": "2",
                                  "socket:type2_combo:output": "150 kW"})
    st = chargers.parse_element(el)
    st.distance_km = 1.0
    out = chargers.geojson_envelope([st], {"near": "46.50,11.35"})
    assert out["type"] == "FeatureCollection"
    assert "metadata" in out and "source" in out["metadata"]
    assert len(out["features"]) == 1
    feat = out["features"][0]
    assert feat["type"] == "Feature"
    assert feat["geometry"]["type"] == "Point"
    # GeoJSON convention: [lon, lat]
    assert feat["geometry"]["coordinates"] == [11.35, 46.50]
    assert "lat" not in feat["properties"]
    assert "lon" not in feat["properties"]


def test_mcp_find_chargers_normalizes_bilingual_comune(monkeypatch):
    """MCP path must resolve "Bozen" -> "BOLZANO" like the CLI does."""
    pytest.importorskip("mcp")  # the [mcp] extra is optional; skip in CI test job
    from pitstop import mcp_server
    # No real network: serve a small coords table and a fake Overpass response.
    monkeypatch.setattr(
        mcp_server.geocoding, "load_comune_coords",
        lambda *a, **k: {"BOLZANO": (46.498, 11.354)},
    )
    monkeypatch.setattr(
        mcp_server.ev_chargers.overpass, "fetch_elements",
        lambda *a, **k: (
            [_node(99, 46.498, 11.354, {"amenity": "charging_station",
                                         "operator": "Alperia",
                                         "socket:type2": "1"})],
            None,
        ),
    )
    # FastMCP tools wrap the function; the underlying impl is preserved as fn
    # when callable, otherwise call_tool via asyncio. Try the simpler path.
    result = mcp_server.find_chargers(comune="Bozen", radius_km=3, limit=1)
    assert "error" not in result, f"got error: {result.get('error')}"
    assert result["count"] == 1
    assert result["stations"][0]["operator"] == "Alperia"
