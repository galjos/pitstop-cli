"""pitstop command-line surface: JSON-first, stdlib-only.

Exit codes: 0 success, 1 runtime error, 2 usage error."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error

from . import core
from .version import __version__


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
    stations.add_argument("--no-comune-validate", dest="validate_comune", action="store_false",
                          help="skip validating coordinates against the comune-coords reference")
    stations.add_argument("--limit", type=int, default=20, help="max stations; 0 = no limit")
    stations.set_defaults(func=_cmd_stations)

    fuels = sub.add_parser("fuels", help="list the fuel types present in the dataset")
    _add_load_args(fuels)
    fuels.set_defaults(func=_cmd_fuels)

    version = sub.add_parser("version", help="print version metadata")
    version.set_defaults(func=lambda _a: (print(f"pitstop {__version__}") or 0))

    return p


def _add_load_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--json", dest="as_json", action="store_true", help="emit JSON instead of a table")
    sp.add_argument("--refresh", action="store_true", help="bypass cache and re-download source files")
    sp.add_argument("--max-age", type=int, default=core.DEFAULT_MAX_AGE,
                    help="seconds a cached file stays fresh")
    sp.add_argument("--timeout", type=int, default=core.DEFAULT_TIMEOUT,
                    help="per-request download timeout in seconds")


def _load(args) -> core.Dataset:
    return core.load(refresh=args.refresh, max_age=args.max_age, timeout=args.timeout)


def _cmd_stations(args) -> int:
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

    out = core.query_stations(
        ds,
        comune=args.comune,
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
        validate_comune=args.validate_comune,
        limit=args.limit,
    )

    query: dict = {}
    for key, val in (("comune", args.comune), ("provincia", args.provincia),
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

    if args.as_json:
        return _print_stations_json(ds, out, query)
    return _print_stations_table(out, use_near)


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


def _print_stations_table(stations: list[core.Station], use_near: bool) -> int:
    any_suspect = False
    any_outlier = False
    rows = []
    for st in stations:
        prices = st.prices or [None]
        for p in prices:
            mode = "" if p is None else ("self" if p.self_service else "served")
            fuel = "" if p is None else p.fuel
            if p is None:
                price = ""
            else:
                outlier_mark = " ?" if p.outlier else ""
                price = f"{p.price:.3f}{outlier_mark}"
                if p.outlier:
                    any_outlier = True
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
    if any_outlier:
        print("\n? price >15% below its (fuel, provincia) median — may be a misreport.")
    if any_suspect:
        print("* coordinate_suspect: registry coordinate is far from the comune's other stations.")
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
