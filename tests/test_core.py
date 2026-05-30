from datetime import date
from pathlib import Path

import pytest

from pitstop import core

REGISTRY = """\
Estrazione del 2026-05-28
idImpianto|Gestore|Bandiera|Tipo Impianto|Nome Impianto|Indirizzo|Comune|Provincia|Latitudine|Longitudine
1|OP A|BrandA|Stradale|Station A|Via A 1|ROMA|RM|41.9028|12.4964
2|OP B|BrandB|Stradale|Station B|Via B 2, ang. Via X|MILANO|MI|45.4642|9.1900
3|OP C|BrandC|Autostradale|Station C|Via C 3|BOLZANO|BZ|46.4983|11.3548
"""

PRICES = """\
Estrazione del 2026-05-28
idImpianto|descCarburante|prezzo|isSelf|dtComu
1|Benzina|1.899|1|27/05/2026 21:30:07
1|Gasolio|1.799|0|27/05/2026 21:30:07
1|Gasolio Oro Diesel|1.000|1|27/05/2026 21:30:07
2|Benzina|1.950|0|27/05/2026 10:00:00
3|GPL|0.750|1|27/05/2026 09:00:00
999|Benzina|9.999|1|27/05/2026 09:00:00
"""


@pytest.fixture
def registry_path(tmp_path: Path) -> Path:
    p = tmp_path / "anagrafica.csv"
    p.write_text(REGISTRY, encoding="utf-8")
    return p


@pytest.fixture
def prices_path(tmp_path: Path) -> Path:
    p = tmp_path / "prezzo.csv"
    p.write_text(PRICES, encoding="utf-8")
    return p


def test_parse_registry(registry_path):
    stations, date = core._parse_registry(registry_path)
    assert date == "2026-05-28"
    assert set(stations) == {"1", "2", "3"}
    rome = stations["1"]
    assert rome.comune == "ROMA"
    assert rome.provincia == "RM"
    assert rome.brand == "BrandA"
    assert rome.lat == pytest.approx(41.9028)
    assert rome.lon == pytest.approx(12.4964)
    # commas inside a pipe-delimited address field stay intact
    assert stations["2"].address == "Via B 2, ang. Via X"


def test_attach_prices_joins_and_skips_unknown(registry_path, prices_path):
    stations, _ = core._parse_registry(registry_path)
    price_date = core._attach_prices(prices_path, stations)
    assert price_date == "2026-05-28"
    assert len(stations["1"].prices) == 3
    assert len(stations["2"].prices) == 1
    assert len(stations["3"].prices) == 1
    # id 999 has no registry entry -> dropped, not created
    assert "999" not in stations


def test_attach_prices_fields(registry_path, prices_path):
    stations, _ = core._parse_registry(registry_path)
    core._attach_prices(prices_path, stations)
    benzina = next(p for p in stations["1"].prices if p.fuel == "Benzina")
    assert benzina.price == pytest.approx(1.899)
    assert benzina.self_service is True
    assert benzina.updated == "2026-05-27T21:30:07"
    gasolio = next(p for p in stations["1"].prices if p.fuel == "Gasolio")
    assert gasolio.self_service is False


def test_filter_prices_fuel_substring():
    prices = [
        core.Price("Gasolio", 1.799, False, ""),
        core.Price("Gasolio Oro Diesel", 1.0, True, ""),
        core.Price("Benzina", 1.899, True, ""),
    ]
    out = core.filter_prices(prices, fuel="gasolio")
    assert {p.fuel for p in out} == {"Gasolio", "Gasolio Oro Diesel"}


def test_filter_prices_self_and_served():
    prices = [
        core.Price("Gasolio", 1.799, False, ""),
        core.Price("Gasolio", 1.699, True, ""),
    ]
    assert [p.price for p in core.filter_prices(prices, self_only=True)] == [1.699]
    assert [p.price for p in core.filter_prices(prices, served_only=True)] == [1.799]


def test_filter_prices_min_price_drops_placeholders():
    prices = [
        core.Price("Gasolio", 1.799, False, ""),
        core.Price("Gasolio Oro Diesel", 1.0, True, ""),
    ]
    out = core.filter_prices(prices, min_price=1.2)
    assert [p.price for p in out] == [1.799]


def test_min_price_helper():
    assert core.min_price_of([core.Price("X", 2.0, True, ""), core.Price("Y", 1.5, True, "")]) == 1.5
    assert core.min_price_of([]) is None


def test_price_age_days():
    today = date(2026, 5, 29)
    assert core.price_age_days("2026-05-27T08:00:00", today) == 2
    assert core.price_age_days("27/05/2023 07:54:52", today) == 1098
    assert core.price_age_days("not a date", today) is None


def test_filter_prices_max_age_drops_stale():
    today = date(2026, 5, 29)
    prices = [
        core.Price("Gasolio", 2.115, True, "2026-05-27T23:38:00"),
        core.Price("Gasolio Alpino", 1.749, True, "2023-06-17T07:54:52"),  # stale
    ]
    out = core.filter_prices(prices, fuel="gasolio", max_age_days=90, today=today)
    assert [p.price for p in out] == [2.115]
    # without the freshness filter, the stale cheap one is kept
    out_all = core.filter_prices(prices, fuel="gasolio", today=today)
    assert len(out_all) == 2


def test_default_floor():
    # petrol/diesel/methane: real prices > placeholder 1.000, so apply a 1.2 floor
    assert core.default_floor("Gasolio") == 1.2
    assert core.default_floor("Benzina") == 1.2
    assert core.default_floor("Metano") == 1.2
    # GPL is genuinely cheaper than 1.000 -> no floor, or all real prices vanish
    assert core.default_floor("GPL") == 0.0
    assert core.default_floor("") == 0.0


def test_in_italy_bbox():
    assert core.in_italy(41.9, 12.5)  # Rome
    assert core.in_italy(46.5, 11.35)  # Bolzano
    assert not core.in_italy(0.0, 0.0)
    assert not core.in_italy(48.85, 2.35)  # Paris
    assert not core.in_italy(40.0, 25.0)  # Aegean


def test_comune_centroids_and_suspect_flag():
    # 3 ROMA stations clustered near Rome + 1 mis-geocoded at Bolzano coords;
    # the cluster of 3 makes ROMA a checkable comune (>=3 stations) and the
    # outlier should be flagged.
    def st(sid, lat, lon):
        return core.Station(sid, "", "", "", f"S{sid}", "", "ROMA", "RM", lat, lon,
                            [core.Price("Benzina", 2.0, True, "2026-05-27T00:00:00")])
    ds = core.Dataset(
        stations={
            "1": st("1", 41.90, 12.49),
            "2": st("2", 41.91, 12.50),
            "3": st("3", 41.89, 12.48),
            "4": st("4", 46.50, 11.35),  # ~430 km from Rome -> suspect
        },
        registry_date="2026-05-28",
        price_date="2026-05-28",
    )
    cents = core.comune_centroids(ds)
    assert "ROMA" in cents
    assert cents["ROMA"][0] == pytest.approx(41.90, abs=0.05)

    out = core.query_stations(ds, comune="ROMA", limit=0)
    flagged = {s.id: s.coordinate_suspect for s in out}
    assert flagged == {"1": False, "2": False, "3": False, "4": True}


def test_query_stations_uses_true_comune_coord_to_flag_single_station_comune():
    # Single-station comune: centroid heuristic can't help; only the true
    # comune coord (from the second source) can flag it.
    bad = core.Station("X", "", "", "", "Rasen", "", "RASUN-ANTERSELVA", "BZ",
                       46.4545, 11.3188,  # registry-stored (wrong)
                       [core.Price("Gasolio", 2.115, True, "2026-05-27T00:00:00")])
    ds = core.Dataset(stations={"X": bad}, registry_date="2026-05-28", price_date="2026-05-28")
    coords = {"RASUN-ANTERSELVA": (46.839, 12.112)}  # true coord
    out = core.query_stations(ds, comune_coords=coords)
    assert out[0].coordinate_suspect is True
    # Without comune validation, single-station comune isn't flagged.
    bad.coordinate_suspect = False
    out2 = core.query_stations(ds, validate_comune=False, comune_coords={})
    assert out2[0].coordinate_suspect is False


def test_query_stations_near_rejects_far_comune():
    # The Rasen case: stored coord lands ~5km from Bolzano so it passes the
    # radius check, but the declared comune's true location is ~50km away ->
    # excluded by the comune sanity check.
    rasen = core.Station("R", "", "", "", "Rasen", "", "RASUN-ANTERSELVA", "BZ",
                         46.4545, 11.3188,
                         [core.Price("Gasolio", 1.749, True, "2026-05-27T00:00:00")])
    bolzano = core.Station("B", "", "", "", "BZ Station", "", "BOLZANO", "BZ",
                           46.498, 11.354,
                           [core.Price("Gasolio", 2.0, True, "2026-05-27T00:00:00")])
    ds = core.Dataset(stations={"R": rasen, "B": bolzano},
                      registry_date="2026-05-28", price_date="2026-05-28")
    coords = {"RASUN-ANTERSELVA": (46.839, 12.112), "BOLZANO": (46.498, 11.354)}
    out = core.query_stations(ds, near=(46.498, 11.354), radius_km=6, comune_coords=coords)
    assert [s.id for s in out] == ["B"]


def test_query_stations_skips_invalid_coords_for_near():
    bad = core.Station("X", "", "", "", "S", "", "NOWHERE", "ZZ", 0.0, 0.0,
                       [core.Price("Benzina", 2.0, True, "2026-05-27T00:00:00")])
    good = core.Station("Y", "", "", "", "S", "", "ROMA", "RM", 41.90, 12.50,
                        [core.Price("Benzina", 2.0, True, "2026-05-27T00:00:00")])
    ds = core.Dataset(
        stations={"X": bad, "Y": good},
        registry_date="2026-05-28", price_date="2026-05-28",
    )
    out = core.query_stations(ds, near=(41.90, 12.50), radius_km=10)
    assert [s.id for s in out] == ["Y"]


def test_haversine_zero_and_known():
    assert core.haversine_km(41.9, 12.5, 41.9, 12.5) == pytest.approx(0.0, abs=1e-9)
    # Rome -> Milano is roughly 477 km
    d = core.haversine_km(41.9028, 12.4964, 45.4642, 9.1900)
    assert 470 < d < 485


def test_to_float():
    assert core._to_float("1.799") == pytest.approx(1.799)
    assert core._to_float("1,799") == pytest.approx(1.799)  # comma decimal tolerated
    assert core._to_float("garbage") == 0.0
    assert core._to_float("garbage", default=None) is None


def test_normalize_ts():
    assert core._normalize_ts("27/05/2026 21:30:07") == "2026-05-27T21:30:07"
    assert core._normalize_ts("not a date") == "not a date"
