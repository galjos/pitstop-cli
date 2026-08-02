import re
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


def test_fuel_provincia_medians_and_outlier_flag():
    # Build a synthetic dataset: 15 ROMA stations with diesel ~2.00 + one outlier at 1.50.
    def st(sid, price):
        return core.Station(sid, "", "", "", f"S{sid}", "", "ROMA", "RM", 41.9, 12.5,
                            [core.Price("Gasolio", price, True, "2026-05-27T00:00:00")])
    stations = {str(i): st(str(i), 2.00 + (i - 7) * 0.005) for i in range(15)}
    stations["X"] = st("X", 1.50)
    ds = core.Dataset(stations=stations, registry_date="2026-05-28", price_date="2026-05-28")

    meds = core.fuel_provincia_medians(ds, min_n=10)
    assert ("gasolio", "RM") in meds
    assert 1.99 < meds[("gasolio", "RM")] < 2.01

    out = core.query_stations(ds, validate_comune=False, limit=0)
    outlier = next(s for s in out if s.id == "X")
    normal = next(s for s in out if s.id == "7")
    assert outlier.prices[0].outlier is True
    assert outlier.prices[0].deviation_pct < -20
    assert normal.prices[0].outlier is False
    assert normal.prices[0].regional_median is not None


def test_tukey_fence_catches_borderline_outliers():
    # Build a tight market: 15 prices around 2.10 + one at 1.787 (~-14.9%, just
    # under the 15% rule, but well below the Tukey lower fence). The combined
    # outlier flag must catch it. Mirrors the real BZ Gasolio g.p. oil case.
    def st(sid, price):
        return core.Station(sid, "", "", "", f"S{sid}", "", "BOLZANO", "BZ", 46.5, 11.35,
                            [core.Price("Gasolio", price, True, "2026-05-27T00:00:00")])
    tight = [2.099, 2.099, 2.099, 2.099, 2.099, 2.069, 2.069, 2.069,
             2.129, 2.129, 2.129, 2.149, 2.149, 2.059, 2.069]
    stations = {str(i): st(str(i), p) for i, p in enumerate(tight)}
    stations["X"] = st("X", 1.787)
    ds = core.Dataset(stations=stations, registry_date="2026-05-28", price_date="2026-05-28")

    out = core.query_stations(ds, validate_comune=False, limit=0)
    outlier = next(s for s in out if s.id == "X")
    assert -15.0 < outlier.prices[0].deviation_pct < -14.5, "should be within the percent rule"
    assert outlier.prices[0].outlier is True, "Tukey fence should still flag it"

    # drop_outliers removes it
    out_dropped = core.query_stations(ds, fuel="Gasolio", drop_outliers=True,
                                       validate_comune=False, limit=0)
    assert "X" not in {s.id for s in out_dropped}


def test_outlier_rule_docs_describe_both_halves():
    """Every user-facing description of the outlier rule must state both halves
    (percent OR Tukey fence) and, for unscreened prices, that no check ran. Only
    core.QUALITY_NOTE may name MIN_SAMPLES_FOR_MEDIAN, and by interpolating it."""
    from pitstop import cli, mcp_server
    root = Path(__file__).resolve().parents[1]
    skill = (root / "skills" / "pitstop" / "SKILL.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    for text, label in ((skill, "SKILL.md"),
                        (readme, "README.md"),
                        (mcp_server._CAVEATS, "mcp_server._CAVEATS"),
                        (cli._OUTLIER_LEGEND, "cli._OUTLIER_LEGEND")):
        assert "15%" in text, f"{label} lost the percent half of the outlier rule"
        assert "Tukey" in text, f"{label} lost the Tukey half of the outlier rule"

    for text, label in ((skill, "SKILL.md"),
                        (readme, "README.md"),
                        (mcp_server._CAVEATS, "mcp_server._CAVEATS"),
                        (cli._UNSCREENED_LEGEND, "cli._UNSCREENED_LEGEND"),
                        (core.QUALITY_NOTE, "core.QUALITY_NOTE")):
        assert "no outlier check ran" in text, \
            f"{label} stopped saying that no outlier check ran on unscreened prices"
        if label == "core.QUALITY_NOTE":
            assert str(core.MIN_SAMPLES_FOR_MEDIAN) in text
            continue
        assert not re.search(r"\b\d+ samples", text), \
            f"{label} hardcodes the sample threshold instead of leaving it to core"


def test_unscreened_price_is_labelled_and_counted():
    # Thin bucket: 3 "Metano" prices in RM is below MIN_SAMPLES_FOR_MEDIAN, so no
    # median exists and no outlier check runs.
    def st(sid, fuel, price):
        return core.Station(sid, "", "", "", f"S{sid}", "", "ROMA", "RM", 41.9, 12.5,
                            [core.Price(fuel, price, True, "2026-05-27T00:00:00")])
    stations = {str(i): st(str(i), "Gasolio", 2.00) for i in range(15)}
    for i in range(3):
        stations[f"M{i}"] = st(f"M{i}", "Metano", 1.50)
    ds = core.Dataset(stations=stations, registry_date="2026-05-28", price_date="2026-05-28")

    out = core.query_stations(ds, validate_comune=False, limit=0)
    thick = next(s for s in out if s.id == "0").prices[0]
    thin = next(s for s in out if s.id == "M0").prices[0]

    assert thick.median_basis == "screened"
    assert thin.median_basis == "unscreened"
    assert thin.regional_median is None and thin.outlier is False

    d_thick, d_thin = thick.to_dict(), thin.to_dict()
    assert d_thick["median_basis"] == "screened"
    assert d_thin["median_basis"] == "unscreened"
    # Neither carries `outlier`, which is why `median_basis` is unconditional.
    assert "outlier" not in d_thick and "outlier" not in d_thin
    # Additive only: the pre-existing keys are untouched.
    assert d_thick["regional_median"] == thick.regional_median
    assert "regional_median" not in d_thin

    env = core.response_envelope(ds, out, {})
    assert env["quality"] == {"prices": 18, "screened": 15, "unscreened": 3,
                              "outliers": 0, "note": core.QUALITY_NOTE}
    assert str(core.MIN_SAMPLES_FOR_MEDIAN) in env["quality"]["note"]


def test_table_marks_unscreened_prices(capsys):
    """The table must mark an unscreened price, not print it like a clean one."""
    from pitstop import cli

    def st(sid, fuel, price):
        return core.Station(sid, "", "", "", f"S{sid}", "", "ROMA", "RM", 41.9, 12.5,
                            [core.Price(fuel, price, True, "2026-05-27T00:00:00")])
    stations = {str(i): st(str(i), "Gasolio", 2.00) for i in range(15)}
    stations["M"] = st("M", "Metano", 1.50)  # thin bucket -> unscreened
    ds = core.Dataset(stations=stations, registry_date="2026-05-28", price_date="2026-05-28")
    out = core.query_stations(ds, validate_comune=False, limit=0)

    cli._print_stations_table(ds, out, False)
    text = capsys.readouterr().out
    assert "1.500 ~" in next(l for l in text.splitlines() if "Metano" in l)
    assert "2.000 ~" not in next(l for l in text.splitlines() if "Gasolio" in l)
    assert cli._UNSCREENED_LEGEND in text

    # The legend is conditional: an all-screened answer must not print it.
    cli._print_stations_table(ds, [s for s in out if s.id != "M"], False)
    assert cli._UNSCREENED_LEGEND not in capsys.readouterr().out


def test_max_deviation_pct_filters_outliers():
    def st(sid, price):
        return core.Station(sid, "", "", "", f"S{sid}", "", "ROMA", "RM", 41.9, 12.5,
                            [core.Price("Gasolio", price, True, "2026-05-27T00:00:00")])
    stations = {str(i): st(str(i), 2.00) for i in range(15)}
    stations["X"] = st("X", 1.50)
    ds = core.Dataset(stations=stations, registry_date="2026-05-28", price_date="2026-05-28")

    out = core.query_stations(ds, fuel="Gasolio", max_deviation_pct=20,
                              validate_comune=False, limit=0)
    assert "X" not in {s.id for s in out}


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


# ---- v0.9.0 additions: multi-fuel, bilingual comuni, stats, geo, navigation ----


def test_filter_prices_multi_fuel_comma_list():
    prices = [
        core.Price("Benzina", 1.9, True, ""),
        core.Price("Gasolio", 2.0, True, ""),
        core.Price("GPL", 0.8, True, ""),
    ]
    out = core.filter_prices(prices, fuel="Benzina,Gasolio")
    assert {p.fuel for p in out} == {"Benzina", "Gasolio"}
    # spaces between commas tolerated
    assert {p.fuel for p in core.filter_prices(prices, fuel=" Benzina , GPL ")} == {"Benzina", "GPL"}


def test_normalize_comune_bilingual():
    from pitstop import geocoding
    assert geocoding.normalize_comune("Bozen") == "BOLZANO"
    assert geocoding.normalize_comune("Rome") == "ROMA"
    assert geocoding.normalize_comune("Mailand") == "MILANO"
    assert geocoding.normalize_comune("Brixen") == "BRESSANONE"
    assert geocoding.normalize_comune("Venise") == "VENEZIA"  # French
    # Italian/already-uppercase passes through unchanged.
    assert geocoding.normalize_comune("bolzano") == "BOLZANO"
    assert geocoding.normalize_comune("MILANO") == "MILANO"
    # Empty / whitespace
    assert geocoding.normalize_comune("") == ""
    assert geocoding.normalize_comune("   ") == ""


def test_bilingual_map_has_no_identity_or_duplicate_entries():
    from pitstop import geocoding
    identity = [k for k, v in geocoding.BILINGUAL_MAP.items() if k == v]
    assert identity == [], f"identity mappings in BILINGUAL_MAP: {identity}"


def test_navigation_url_format():
    url = core.navigation_url(46.498, 11.354)
    assert url.startswith("https://")
    assert "google" in url and "maps" in url
    assert "46.498" in url and "11.354" in url


def test_fuel_stats_shape(registry_path, prices_path):
    stations, _ = core._parse_registry(registry_path)
    core._attach_prices(prices_path, stations)
    ds = core.Dataset(stations=stations, registry_date="2026-05-28", price_date="2026-05-28")
    stats = core.fuel_stats(ds, fuel="Benzina")
    assert "Benzina" in stats
    benz = stats["Benzina"]
    assert "provinces" in benz and "national" in benz
    assert set(benz["provinces"]) == {"RM", "MI"}
    rm = benz["provinces"]["RM"]
    assert rm["count"] == 1
    assert rm["median"] == pytest.approx(1.899, abs=1e-3)
    nat = benz["national"]
    assert nat["count"] == 2  # one RM + one MI


def test_geojson_envelope_shape(registry_path, prices_path):
    stations, _ = core._parse_registry(registry_path)
    core._attach_prices(prices_path, stations)
    ds = core.Dataset(stations=stations, registry_date="2026-05-28", price_date="2026-05-28")
    out = core.geojson_envelope(ds, list(stations.values())[:2], {"comune": "ROMA"})
    assert out["type"] == "FeatureCollection"
    assert out["metadata"]["registry_extraction_date"] == "2026-05-28"
    assert len(out["features"]) == 2
    feat = out["features"][0]
    assert feat["type"] == "Feature"
    assert feat["geometry"]["type"] == "Point"
    # GeoJSON is [lon, lat] (NOT [lat, lon])
    assert len(feat["geometry"]["coordinates"]) == 2
    assert feat["geometry"]["coordinates"][0] == pytest.approx(stations["1"].lon, abs=1e-4)
    assert feat["geometry"]["coordinates"][1] == pytest.approx(stations["1"].lat, abs=1e-4)
    # Coordinates must not be duplicated inside properties.
    assert "lat" not in feat["properties"]
    assert "lon" not in feat["properties"]


# ---- MIMIT serves its maintenance page with HTTP 200: never cache that ----

_MAINTENANCE_PAGE = b"<!DOCTYPE html>\n<html><body>Servizio non disponibile</body></html>"
_GOOD_CSV = (
    b"Estrazione del 2026-07-31\n"
    b"idImpianto|descCarburante|prezzo|isSelf|dtComu\n"
    b"1|Benzina|1.999|1|2026-07-30T08:00:00\n"
)


def _serve_body(monkeypatch, tmp_path, body: bytes):
    """Point the MIMIT cache at tmp_path and answer every download with `body`."""
    monkeypatch.setattr(core, "cache_dir", lambda: tmp_path)

    class _Resp:
        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(core.urllib.request, "urlopen", lambda *a, **k: _Resp())


def test_error_page_does_not_clobber_a_good_mimit_cache(monkeypatch, tmp_path):
    cached = tmp_path / "prezzo_alle_8.csv"
    cached.write_bytes(_GOOD_CSV)
    _serve_body(monkeypatch, tmp_path, _MAINTENANCE_PAGE)

    path = core._cached_file(
        "https://example.test/p.csv", "prezzo_alle_8.csv",
        refresh=True, max_age=0, timeout=5,
    )
    assert path.read_bytes() == _GOOD_CSV, "the maintenance page overwrote the cache"


def test_error_page_with_no_cache_raises_rather_than_parsing_html(monkeypatch, tmp_path):
    _serve_body(monkeypatch, tmp_path, _MAINTENANCE_PAGE)

    with pytest.raises(ValueError, match="maintenance page"):
        core._cached_file(
            "https://example.test/p.csv", "prezzo_alle_8.csv",
            refresh=True, max_age=0, timeout=5,
        )
    assert not (tmp_path / "prezzo_alle_8.csv").exists()


def test_valid_mimit_download_is_cached(monkeypatch, tmp_path):
    _serve_body(monkeypatch, tmp_path, _GOOD_CSV)

    path = core._cached_file(
        "https://example.test/p.csv", "prezzo_alle_8.csv",
        refresh=True, max_age=0, timeout=5,
    )
    assert path.read_bytes() == _GOOD_CSV


def test_ev_tariff_docs_claim_only_what_pitstop_parses():
    """pitstop must describe its own parser, not OpenStreetMap's contents: some
    OSM nodes do carry a free-text `charge` tag, so "carry only fee" is false.
    Also keeps dated third-party survey claims off every shipped surface."""
    from pitstop import chargers, cli, cpo_tariffs, mcp_server
    root = Path(__file__).resolve().parents[1]
    surfaces = {
        "SKILL.md": (root / "skills" / "pitstop" / "SKILL.md").read_text(encoding="utf-8"),
        "README.md": (root / "README.md").read_text(encoding="utf-8"),
        "mcp_server._FIND_CHARGERS_DESC": mcp_server._FIND_CHARGERS_DESC,
        "chargers disclaimer": chargers.response_envelope([], {})["disclaimer"],
        "chargers.__doc__": chargers.__doc__,
        "cpo_tariffs.__doc__": cpo_tariffs.__doc__,
        "cli.__doc__": cli.__doc__ or "",
    }
    banned = ("carry only `fee`", "carry only fee", "as of mid-2026",
              "AFIR", "Chargeprice", "Eco-Movement")
    for label, text in surfaces.items():
        for phrase in banned:
            assert phrase not in text, (
                f"{label} reintroduced an unverifiable claim about the outside world: {phrase!r}"
            )
