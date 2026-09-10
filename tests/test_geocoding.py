import json

import pytest

from pitstop import cli, geocoding


REFERENCE = """comune,pro_com_t,lat,long,sigla
Bolzano,021008,46.655942,11.229637,BZ
Roma,058091,41.89332,12.482932,RM
Livo,013130,46.168845,9.304510,CO
Livo,022106,46.404711,11.019271,TN
"""


@pytest.fixture
def reference(tmp_path, monkeypatch):
    path = tmp_path / "comuni.csv"
    path.write_text(REFERENCE)
    monkeypatch.setattr(geocoding, "_cached_path", lambda *a: path)
    return path


def test_duplicate_names_preserve_province_and_id(reference):
    places = geocoding.find_municipalities("Livo")
    assert [(p.province, p.istat_id) for p in places] == [("CO", "013130"), ("TN", "022106")]
    coords = geocoding._parse_comuni(reference)
    assert "LIVO" not in coords
    assert coords[("LIVO", "CO")] != coords[("LIVO", "TN")]


def test_ambiguous_name_requires_selection_before_overpass(reference, monkeypatch):
    monkeypatch.setattr("pitstop.overpass.fetch_elements", lambda *a, **k: pytest.fail("unexpected fetch"))
    with pytest.raises(ValueError, match="ambiguous.*013130.*022106"):
        geocoding.resolve_municipality("Livo")


@pytest.mark.parametrize("name,province,code,lat,lon", [
    ("Bozen", "", "021008", 46.4984781, 11.3547399),
    ("Rome", "", "058091", 41.8933203, 12.4829321),
    ("Livo", "CO", "013130", 46.1688448, 9.30451),
    ("Livo", "TN", "022106", 46.404711, 11.019271),
    ("", "", "022106", 46.404711, 11.019271),
])
def test_center_is_selected_by_municipality_identity(reference, monkeypatch, name, province, code, lat, lon):
    def fetch(query, **kwargs):
        assert f'["ref:ISTAT"="{code}"]' in query
        return [
            {"type": "relation", "tags": {"ref:ISTAT": code},
             "members": [{"type": "node", "ref": 7, "role": "admin_centre"}]},
            {"type": "node", "id": 7, "lat": lat, "lon": lon},
            {"type": "node", "id": 8, "lat": 0, "lon": 0},
        ], None
    monkeypatch.setattr("pitstop.overpass.fetch_elements", fetch)
    location = geocoding.resolve_municipality(name, province, "" if name else code)
    assert location["comune_id"] == code
    assert (location["lat"], location["lon"]) == (lat, lon)
    if code == "021008":
        assert location["reference_distance_km"] > 19
        assert location["warnings"]


def test_unavailable_center_does_not_use_the_wrong_reference(reference, monkeypatch):
    monkeypatch.setattr("pitstop.overpass.fetch_elements", lambda *a, **k: ([], "HTTP 503"))
    with pytest.raises(OSError, match="no unique mapped center.*503"):
        geocoding.resolve_municipality("Bozen")


def test_places_cli_makes_ambiguous_choices_reviewable(reference, capsys):
    assert cli.main(["places", "Livo", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["count"] == 2
    assert {p["comune_id"] for p in result["places"]} == {"013130", "022106"}


def test_invalid_reference_is_not_reported_as_a_missing_municipality(reference):
    reference.write_text("<html>maintenance</html>")
    with pytest.raises(OSError, match="no usable records"):
        geocoding.resolve_municipality("Bozen")
