"""pitstop command-line surface: JSON-first, stdlib-only.

Exit codes: 0 success, 1 runtime error, 2 usage error."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error

from . import core
from .version import __version__

# Must state both halves of the rule core.query_stations applies, or a Tukey-only
# flagged row prints a legend that is false for that row.
_OUTLIER_LEGEND = (
    "? price >15% below its (fuel, provincia) median, or below that bucket's "
    "Tukey lower fence (Q1-1.5*IQR) — may be a misreport."
)

# Without this mark an unscreened price prints exactly like a screened-and-clean one.
_UNSCREENED_LEGEND = (
    "~ price is unscreened: its (fuel, provincia) bucket held too few samples "
    "for a median, so no outlier check ran on it — it is shown as reported."
)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help(sys.stderr)
        return 2
    try:
        return args.func(args)
    except urllib.error.URLError as e:
        print(f"error: could not fetch source data: {e}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pitstop",
        description=(
            "Unofficial JSON-first CLI for Italian fuel-station prices, backed by "
            "MIMIT Osservaprezzi Carburanti open data."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  pitstop stations --comune ROMA --fuel Gasolio --cheapest --limit 5\n"
            "  pitstop stations --near 46.498,11.354 --radius 5 --fuel Benzina --self --json\n"
            "  pitstop fuels"
        ),
    )
    p.set_defaults(func=None)
    sub = p.add_subparsers(dest="command")

    stations = sub.add_parser("stations", help="list and filter fuel stations with prices")
    _add_load_args(stations)
    stations.add_argument("--comune", default="", help="municipality name (case-insensitive)")
    stations.add_argument("--provincia", default="", help="2-letter province code, e.g. BZ, RM")
    stations.add_argument("--brand", default="", help="brand/bandiera substring (case-insensitive)")
    stations.add_argument("--near", default="", help='proximity to "lat,lon"')
    stations.add_argument("--radius", type=float, default=10.0, help="radius in km for --near")
    stations.add_argument("--fuel", default="", help="keep only this fuel (substring, case-insensitive)")
    stations.add_argument("--self", dest="self_only", action="store_true", help="only self-service prices")
    stations.add_argument("--served", dest="served_only", action="store_true", help="only served prices")
    stations.add_argument("--cheapest", action="store_true", help="sort by ascending price (needs --fuel)")
    stations.add_argument("--min-price", dest="min_price", type=float, default=0.0,
                          help="drop prices below this floor (e.g. 1.2 to skip placeholder values); 0 = off")
    stations.add_argument("--fresh-within-days", dest="fresh_days", type=int, default=0,
                          help="drop prices last updated more than N days ago; 0 = off")
    stations.add_argument("--max-deviation-pct", dest="max_dev_pct", type=float, default=0.0,
                          help="drop prices more than N%% below their (fuel, provincia) median; 0 = off")
    stations.add_argument("--drop-outliers", dest="drop_outliers", action="store_true",
                          help="drop any price flagged outlier (combined 15%% + Tukey IQR rule)")
    stations.add_argument("--no-comune-validate", dest="validate_comune", action="store_false",
                          help="skip validating coordinates against the comune-coords reference")
    stations.add_argument("--limit", type=int, default=20, help="max stations; 0 = no limit")
    stations.set_defaults(func=_cmd_stations)

    fuels = sub.add_parser("fuels", help="list the fuel types present in the dataset")
    _add_load_args(fuels)
    fuels.set_defaults(func=_cmd_fuels)

    stats = sub.add_parser("stats", help="show macro price statistics by province")
    _add_load_args(stats)
    stats.add_argument("--fuel", default="", help="filter stats to these fuels (comma-separated)")
    stats.set_defaults(func=_cmd_stats)

    chargers = sub.add_parser("chargers", help="find EV charging stations (OSM)")
    chargers.add_argument("--near", default="", help='proximity to "lat,lon" (or use --comune)')
    chargers.add_argument("--comune", default="", help="center the search on this Italian comune")
    chargers.add_argument("--radius", type=float, default=10.0, help="radius in km (default 10)")
    chargers.add_argument("--operator", default="", help="operator substring (case-insensitive)")
    chargers.add_argument("--socket", default="", help="plug-type substring, e.g. ccs, chademo, type2")
    chargers.add_argument("--min-power", dest="min_power_kw", type=float, default=0.0,
                          help="minimum max-power kW")
    chargers.add_argument("--fast", action="store_true", help="shortcut for --min-power 50")
    chargers.add_argument("--ultra-fast", dest="ultra_fast", action="store_true",
                          help="shortcut for --min-power 150")
    chargers.add_argument("--free", action="store_true",
                          help="only chargers explicitly free (fee=no); unknown fee is excluded")
    chargers.add_argument("--public", action="store_true",
                          help="only chargers with explicit public/yes/permissive access; unknown access is excluded")
    chargers.add_argument("--limit", type=int, default=20, help="max stations; 0 = no limit")
    chargers.add_argument("--json", dest="as_json", action="store_true")
    chargers.add_argument("--geojson", dest="as_geojson", action="store_true", help="emit GeoJSON FeatureCollection")
    chargers.add_argument("--refresh", action="store_true",
                          help="bypass the 7-day OSM cache")
    chargers.set_defaults(func=_cmd_chargers)

    version = sub.add_parser("version", help="print version metadata")
    version.set_defaults(func=lambda _a: (print(f"pitstop {__version__}") or 0))

    return p


def _add_load_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--json", dest="as_json", action="store_true", help="emit JSON instead of a table")
    sp.add_argument("--geojson", dest="as_geojson", action="store_true", help="emit GeoJSON FeatureCollection")
    sp.add_argument("--refresh", action="store_true", help="bypass cache and re-download source files")
    sp.add_argument("--max-age", type=int, default=core.DEFAULT_MAX_AGE,
                    help="seconds a cached file stays fresh")
    sp.add_argument("--timeout", type=int, default=core.DEFAULT_TIMEOUT,
                    help="per-request download timeout in seconds")


def _load(args) -> core.Dataset:
    return core.load(refresh=args.refresh, max_age=args.max_age, timeout=args.timeout)


def _cmd_stations(args) -> int:
    from . import geocoding
    if args.self_only and args.served_only:
        print("error: --self and --served are mutually exclusive", file=sys.stderr)
        return 2
    if args.cheapest and not args.fuel.strip():
        print("error: --cheapest requires --fuel", file=sys.stderr)
        return 2

    use_near = bool(args.near.strip())
    near_lat = near_lon = 0.0
    if use_near:
        try:
            near_lat, near_lon = _parse_latlon(args.near)
        except ValueError as e:
            print(f"error: invalid --near value: {e}", file=sys.stderr)
            return 2

    ds = _load(args)
    comune_norm = geocoding.normalize_comune(args.comune)

    out = core.query_stations(
        ds,
        comune=comune_norm,
        provincia=args.provincia,
        brand=args.brand,
        near=(near_lat, near_lon) if use_near else None,
        radius_km=args.radius,
        fuel=args.fuel,
        self_only=args.self_only,
        served_only=args.served_only,
        cheapest=args.cheapest,
        min_price=args.min_price,
        max_age_days=args.fresh_days,
        max_deviation_pct=args.max_dev_pct,
        drop_outliers=args.drop_outliers,
        validate_comune=args.validate_comune,
        limit=args.limit,
    )

    query: dict = {}
    for key, val in (("comune", comune_norm or args.comune), ("provincia", args.provincia),
                     ("brand", args.brand), ("fuel", args.fuel)):
        if val.strip():
            query[key] = val
    if use_near:
        query["near"] = args.near
        query["radius_km"] = args.radius
    if args.self_only:
        query["self"] = True
    if args.served_only:
        query["served"] = True
    if args.cheapest:
        query["cheapest"] = True
    if args.min_price > 0:
        query["min_price"] = args.min_price
    if args.fresh_days > 0:
        query["fresh_within_days"] = args.fresh_days
    if args.max_dev_pct > 0:
        query["max_deviation_pct"] = args.max_dev_pct
    if args.drop_outliers:
        query["drop_outliers"] = True

    if args.as_json:
        return _print_stations_json(ds, out, query)
    if args.as_geojson:
        return _print_stations_geojson(ds, out, query)
    return _print_stations_table(ds, out, use_near)


def _cmd_stats(args) -> int:
    ds = _load(args)
    stats = core.fuel_stats(ds, fuel=args.fuel)
    
    if args.as_json:
        _dump({
            "source": core.SOURCE_NAME,
            "price_extraction_date": ds.price_date,
            "generated_at": core.now_iso(),
            "stats": stats
        })
        return 0
        
    return _print_stats_table(stats)


def _print_stats_table(stats: dict) -> int:
    for fuel, data in stats.items():
        print(f"\n--- {fuel.upper()} ---")
        print(f"{'PR'.ljust(4)}  {'MEDIAN'.ljust(8)}  {'MIN'.ljust(8)}  {'MAX'.ljust(8)}  {'SAMPLES'}")
        
        # Sort provinces by code
        sorted_provs = sorted(data["provinces"].items())
        for prov, p_stats in sorted_provs:
            print(f"{prov.ljust(4)}  "
                  f"{p_stats['median']:<8.3f}  "
                  f"{p_stats['min']:<8.3f}  "
                  f"{p_stats['max']:<8.3f}  "
                  f"{p_stats['count']}")
                  
        nat = data["national"]
        print(f"{'---'.ljust(4)}  {'---'.ljust(8)}  {'---'.ljust(8)}  {'---'.ljust(8)}  {'---'}")
        print(f"{'NAT'.ljust(4)}  "
              f"{nat['median']:<8.3f}  "
              f"{nat['min']:<8.3f}  "
              f"{nat['max']:<8.3f}  "
              f"{nat['count']}")
    return 0


def _cmd_chargers(args) -> int:
    from . import chargers, geocoding
    if not args.near.strip() and not args.comune.strip():
        print("error: pass --near \"lat,lon\" or --comune NAME", file=sys.stderr)
        return 2

    if args.near.strip():
        try:
            lat, lon = _parse_latlon(args.near)
        except ValueError as e:
            print(f"error: invalid --near value: {e}", file=sys.stderr)
            return 2
    else:
        coords = geocoding.load_comune_coords()
        comune_norm = geocoding.normalize_comune(args.comune)
        true = coords.get(comune_norm)
        if not true:
            print(f"error: comune '{args.comune}' not found in the comune-coords reference",
                  file=sys.stderr)
            return 1
        lat, lon = true

    min_kw = args.min_power_kw
    if args.ultra_fast:
        min_kw = max(min_kw, 150.0)
    elif args.fast:
        min_kw = max(min_kw, 50.0)

    stations, error = chargers.find_chargers(
        near=(lat, lon),
        radius_km=args.radius,
        operator=args.operator,
        socket=args.socket,
        min_power_kw=min_kw,
        free_only=args.free,
        public_only=args.public,
        refresh=args.refresh,
    )
    if args.limit > 0:
        stations = stations[: args.limit]

    query = {"near": f"{lat},{lon}", "radius_km": args.radius}
    if args.comune:
        query["comune"] = args.comune
    if args.operator:
        query["operator"] = args.operator
    if args.socket:
        query["socket"] = args.socket
    if min_kw > 0:
        query["min_power_kw"] = min_kw
    if args.free:
        query["free"] = True
    if args.public:
        query["public"] = True

    if args.as_json:
        _dump(chargers.response_envelope(stations, query, error=error))
        return 0
    if args.as_geojson:
        _dump(chargers.geojson_envelope(stations, query, error=error))
        return 0
    if error:
        # The JSON paths carry `error` in the envelope; the table has nowhere to
        # put it, so an empty or stale result set would look like a complete one.
        print(f"warning: charger data may be incomplete: {error}", file=sys.stderr)
    return _print_chargers_table(stations)


def _print_chargers_table(stations) -> int:
    headers = ["DIST_KM", "OPERATOR", "MAX_KW", "PLUGS", "CAP", "FEE", "ACCESS", "NAME"]
    rows = [headers]
    for st in stations:
        plugs = ", ".join(f"{s.type}x{s.count}" for s in st.sockets[:3]) or "?"
        fee = "" if st.fee is None else ("yes" if st.fee else "no")
        rows.append([
            f"{st.distance_km:.2f}" if st.distance_km is not None else "",
            (st.operator or "?")[:24],
            f"{st.max_power_kw:g}" if st.max_power_kw is not None else "?",
            plugs[:36],
            str(st.capacity) if st.capacity is not None else "",
            fee,
            (st.access or "")[:10],
            (st.name or "")[:30],
        ])
    widths = [max(len(r[i]) for r in rows) for i in range(len(headers))]
    for r in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))

    if stations:
        top = stations[0]
        print(f"\nTop result map: {core.navigation_url(top.lat, top.lon)}")

    with_tariff = sum(1 for s in stations if s.tariff_info_url)
    if with_tariff:
        print(f"\n{with_tariff}/{len(stations)} stations have an operator tariff page "
              f"(--json to see `tariff_info_url`).")
    # Unconditional: the rows least likely to carry a tariff link are those with an
    # unrecognized operator, which is where a reader most needs telling that FEE is
    # a flag and not a price.
    if stations:
        print("\nThis table reports OSM's fee yes/no flag; pitstop never reports a price per kWh.")
    # ODbL attribution belongs on every surface, not only the JSON envelope.
    from . import overpass
    print(f"\nSource: {overpass.SOURCE_NAME}.")
    return 0


def _cmd_fuels(args) -> int:
    ds = _load(args)
    counts: dict[str, int] = {}
    for st in ds.stations.values():
        for p in st.prices:
            counts[p.fuel] = counts.get(p.fuel, 0) + 1
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    if args.as_json:
        _dump({
            "source": core.SOURCE_NAME,
            "source_url": core.SOURCE_URL,
            "price_extraction_date": ds.price_date,
            "fuels": [{"fuel": f, "count": c} for f, c in items],
        })
        return 0

    width = max((len(f) for f, _ in items), default=4)
    print(f"{'FUEL'.ljust(width)}  PRICE ROWS")
    for f, c in items:
        print(f"{f.ljust(width)}  {c}")
    return 0


def _print_stations_json(ds: core.Dataset, stations: list[core.Station], query: dict) -> int:
    _dump(core.response_envelope(ds, stations, query))
    return 0


def _print_stations_geojson(ds: core.Dataset, stations: list[core.Station], query: dict) -> int:
    _dump(core.geojson_envelope(ds, stations, query))
    return 0


def _print_stations_table(ds: core.Dataset, stations: list[core.Station], use_near: bool) -> int:
    any_suspect = False
    any_outlier = False
    any_unscreened = False
    rows = []
    for st in stations:
        prices = st.prices or [None]
        for p in prices:
            mode = "" if p is None else ("self" if p.self_service else "served")
            fuel = "" if p is None else p.fuel
            if p is None:
                price = ""
            else:
                # Mutually exclusive by construction: `outlier` can only be set
                # once a median existed, which is what `unscreened` says it did not.
                if p.outlier:
                    mark = " ?"
                    any_outlier = True
                elif p.median_basis == "unscreened":
                    mark = " ~"
                    any_unscreened = True
                else:
                    mark = ""
                price = f"{p.price:.3f}{mark}"
            updated = "" if p is None else (p.updated[:10])
            name = st.name + (" *" if st.coordinate_suspect else "")
            if st.coordinate_suspect:
                any_suspect = True
            base = [st.brand, st.comune, st.provincia, fuel, price, mode, updated, name]
            if use_near:
                base = [f"{st.distance_km:.2f}"] + base
            rows.append(base)

    headers = (["DIST_KM"] if use_near else []) + ["BRAND", "COMUNE", "PR", "FUEL", "PRICE", "MODE", "UPDATED", "NAME"]
    rows.insert(0, headers)
    widths = [max(len(r[i]) for r in rows) for i in range(len(headers))]
    for r in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)))

    if stations:
        top = stations[0]
        print(f"\nTop result map: {core.navigation_url(top.lat, top.lon)}")

    legends = ([_OUTLIER_LEGEND] if any_outlier else []) + \
              ([_UNSCREENED_LEGEND] if any_unscreened else [])
    if legends:
        print("\n" + "\n".join(legends))
    if any_suspect:
        print("* coordinate_suspect: registry coordinate is far from the comune's other stations.")
    # Every surface must name MIMIT and the data's age; --json carries it as fields.
    print(f"\nSource: {core.SOURCE_NAME} — prices extracted {ds.price_date}, "
          f"registry {ds.registry_date}.")
    return 0


def _parse_latlon(s: str) -> tuple[float, float]:
    parts = s.split(",")
    if len(parts) != 2:
        raise ValueError('expected "lat,lon"')
    return float(parts[0].strip()), float(parts[1].strip())


def _dump(obj) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
