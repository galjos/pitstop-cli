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
    monkeypatch.setattr(chargers.overpass, "fetch_elements", lambda *a, **k: elements)
    fast = chargers.find_chargers(near=(46.50, 11.35), radius_km=5, min_power_kw=50)
    assert [s.osm_id for s in fast] == [11]


def test_find_chargers_filters_operator(monkeypatch):
    elements = [
        _node(20, 46.50, 11.35, {"amenity": "charging_station", "operator": "Alperia",
                                 "socket:type2": "1"}),
        _node(21, 46.50, 11.35, {"amenity": "charging_station", "operator": "Be Charge",
                                 "socket:type2": "1"}),
    ]
    monkeypatch.setattr(chargers.overpass, "fetch_elements", lambda *a, **k: elements)
    only = chargers.find_chargers(near=(46.50, 11.35), radius_km=5, operator="alperia")
    assert [s.osm_id for s in only] == [20]
