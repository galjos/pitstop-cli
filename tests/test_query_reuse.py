from concurrent.futures import ThreadPoolExecutor
from datetime import date

from pitstop import core


def dataset():
    return core.Dataset({str(i): core.Station(str(i), "", "", "", "Station", "", "ROMA", "RM",
                                            41.9, 12.5,
                                            [core.Price("Benzina", 1.8 + i / 100, True, date.today().isoformat()),
                                             core.Price("Gasolio", 1.7 + i / 100, True, date.today().isoformat())])
                         for i in range(20)}, "2026-09-10", "2026-09-10")


def test_concurrent_queries_do_not_narrow_the_shared_dataset():
    ds = dataset()
    def query(fuel):
        return core.query_stations(ds, fuel=fuel, limit=3, validate_comune=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        petrol, diesel = list(pool.map(query, ["Benzina", "Gasolio"]))
    assert {p.fuel for s in petrol for p in s.prices} == {"Benzina"}
    assert {p.fuel for s in diesel for p in s.prices} == {"Gasolio"}
    assert all(len(s.prices) == 2 for s in ds.stations.values())
    assert all(p.median_basis == "unscreened" for s in ds.stations.values() for p in s.prices)
    petrol[0].prices[0].price = 0
    assert ds.stations["0"].prices[0].price == 1.8
    assert petrol.coverage == {"fetched_count": 20, "matched_count": 20, "returned_count": 3, "truncated": True}


def test_duplicate_municipality_centroids_stay_separate():
    ds = dataset()
    for i, station in enumerate(ds.stations.values()):
        station.comune = "LIVO"
        station.provincia = "CO" if i < 10 else "TN"
        station.lat, station.lon = (46.17, 9.30) if i < 10 else (46.40, 11.02)
    centroids = core.comune_centroids(ds)
    assert "LIVO" not in centroids
    assert centroids[("LIVO", "CO")] == (46.17, 9.30)
    assert centroids[("LIVO", "TN")] == (46.40, 11.02)
