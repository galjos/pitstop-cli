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
