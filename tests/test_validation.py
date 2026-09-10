import pytest

from pitstop import cli, core, mcp_server


@pytest.mark.parametrize("command", ["stations", "chargers"])
@pytest.mark.parametrize("flags", [
    ["--near", "nan,11.354"],
    ["--near", "46.498,inf"],
    ["--near", "91,11.354"],
    ["--near", "46.498,181"],
    ["--near", "46.498,11.354", "--radius", "-1"],
    ["--near", "46.498,11.354", "--radius", "0"],
    ["--near", "46.498,11.354", "--radius", "nan"],
    ["--near", "46.498,11.354", "--limit", "-1"],
    ["--near", "46.498,11.354", "--timeout", "0"],
    ["--near", "46.498,11.354", "--max-age", "-1"],
])
def test_cli_rejects_invalid_search_before_fetch(command, flags, monkeypatch, capsys):
    def unexpected_fetch(*args, **kwargs):
        pytest.fail("invalid input must be rejected before fetching data")

    monkeypatch.setattr(core, "load", unexpected_fetch)
    monkeypatch.setattr("pitstop.geocoding.load_comune_coords", unexpected_fetch)
    monkeypatch.setattr("pitstop.overpass.fetch_elements", unexpected_fetch)
    assert cli.main([command, *flags, "--json"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "error:" in output.err


@pytest.mark.parametrize("tool,arguments", [
    (mcp_server.find_stations, {"near": "nan,11.354"}),
    (mcp_server.find_cheapest, {"fuel": "Gasolio", "radius_km": -1}),
    (mcp_server.find_cheapest, {"fuel": "Gasolio", "limit": -1}),
    (mcp_server.find_chargers, {"near": "91,11.354"}),
    (mcp_server.find_chargers, {"comune": "Bozen", "radius_km": float("inf")}),
    (mcp_server.find_stations, {"min_price": float("nan")}),
    (mcp_server.find_stations, {"max_age_days": -1}),
    (mcp_server.find_cheapest, {"fuel": "Gasolio", "min_price": float("nan")}),
    (mcp_server.find_cheapest, {"fuel": "Gasolio", "min_price": float("-inf")}),
    (mcp_server.find_chargers, {"comune": "Bozen", "min_power_kw": -1}),
])
def test_mcp_rejects_invalid_search_before_fetch(tool, arguments, monkeypatch):
    def unexpected_fetch(*args, **kwargs):
        pytest.fail("invalid input must be rejected before fetching data")

    monkeypatch.setattr(core, "load", unexpected_fetch)
    monkeypatch.setattr("pitstop.geocoding.load_comune_coords", unexpected_fetch)
    monkeypatch.setattr("pitstop.overpass.fetch_elements", unexpected_fetch)
    with pytest.raises(ValueError):
        tool(**arguments)


def test_valid_coordinate_boundaries_and_unlimited_results():
    assert cli._parse_latlon("-90,-180") == (-90, -180)
    assert cli._parse_latlon("90,180") == (90, 180)
    ds = core.Dataset(stations={}, registry_date="", price_date="")
    assert core.query_stations(ds, near=(46.498, 11.354), limit=0, comune_coords={}) == []
