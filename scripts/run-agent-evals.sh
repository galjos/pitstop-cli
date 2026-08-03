#!/usr/bin/env sh

set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
tasks_file="$repo_root/evals/agent/tasks.json"
recipes_file="$repo_root/evals/agent/recipes.json"

if [ ! -f "$tasks_file" ]; then
  echo "missing eval task file: $tasks_file" >&2
  exit 1
fi

if [ ! -f "$recipes_file" ]; then
  echo "missing eval recipe file: $recipes_file" >&2
  exit 1
fi

# python3 does the JSON work the sibling odh runner gives to jq: pitstop ships a
# stdlib-only runtime, so its own eval suite must not add a tool to install.
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required for agent evals" >&2
  exit 1
fi

if [ -n "${PITSTOP_EVAL_BIN:-}" ]; then
  pitstop_cmd="$PITSTOP_EVAL_BIN"
else
  pitstop_cmd="python3 -m pitstop"
  PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"
  export PYTHONPATH
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT HUP INT TERM

cat >"$tmpdir/assert.py" <<'PY'
"""Evaluate one assertion expression against a JSON file; exit 0 when it is true.

The expression sees the document as `d` plus the helpers defined here."""

import json
import re
import sys


def prices(doc):
    """Every price row in a `stations` envelope, across all stations."""
    return [p for s in doc["stations"] for p in s["prices"]]


def station_min(doc):
    """Cheapest price per station, in the order the envelope returned them."""
    return [min(p["price"] for p in s["prices"]) for s in doc["stations"] if s["prices"]]


def is_date(value):
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)))


def is_iso_utc(value):
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", str(value)))


def overpass_error_is_honest(doc):
    """Whether a populated `error` blames the upstream and not pitstop's request.
    A 4xx other than 403/429 means pitstop asked the wrong question (query
    syntax, endpoint, user agent). 429 is Overpass shedding load and 403 is it
    blocking a shared or heavy client IP — neither is our bug."""
    err = doc.get("error")
    if err is None:
        return True
    return (isinstance(err, str) and bool(err.strip())
            and not re.search(r"HTTP Error 4(?!03|29)\d\d", err))


path, expr = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    d = json.load(fh)

ns = {
    "d": d,
    "re": re,
    "prices": prices,
    "station_min": station_min,
    "is_date": is_date,
    "is_iso_utc": is_iso_utc,
    "overpass_error_is_honest": overpass_error_is_honest,
}
# Expressions come from this runner only. A missing key raises rather than
# reading as false, so a renamed field fails the assertion instead of passing it.
try:
    ok = eval(expr, ns)
except Exception as e:
    print(f"expression raised {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(1)
sys.exit(0 if ok else 1)
PY

cat >"$tmpdir/parse_commands.py" <<'PY'
"""Every command string in an eval file must parse against the shipped CLI parser:
a guide that emits commands the CLI rejects is worse than no guide."""

import contextlib
import io
import json
import shlex
import sys

from pitstop.cli import _build_parser

path, key, field = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, encoding="utf-8") as fh:
    entries = json.load(fh)[key]

parser = _build_parser()
failures = []
checked = 0
for entry in entries:
    for command in entry[field]:
        checked += 1
        argv = shlex.split(command)
        if not argv or argv[0] != "pitstop":
            failures.append(f"{entry['id']}: not a pitstop command: {command}")
            continue
        try:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                args = parser.parse_args(argv[1:])
        except SystemExit:
            failures.append(f"{entry['id']}: does not parse ({err.getvalue().strip()}): {command}")
            continue
        if getattr(args, "func", None) is None:
            failures.append(f"{entry['id']}: names no subcommand: {command}")
            continue
        # Usage rules the CLI enforces before it touches data; argparse cannot.
        if getattr(args, "cheapest", False) and not getattr(args, "fuel", "").strip():
            failures.append(f"{entry['id']}: --cheapest without --fuel: {command}")
        if getattr(args, "self_only", False) and getattr(args, "served_only", False):
            failures.append(f"{entry['id']}: --self with --served: {command}")

for failure in failures:
    print(failure, file=sys.stderr)
print(checked)
sys.exit(1 if failures else 0)
PY

cat >"$tmpdir/overpass_state.py" <<'PY'
"""Classify a chargers envelope as `usable` or `degraded`.

`degraded` means Overpass failed and pitstop returned nothing, which is the one
state whose data assertions cannot run — the envelope assertions still do."""

import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    payload = json.load(fh)

# Classify on count alone: Overpass also sheds load with a valid 200 body that
# has no remark and no elements, which leaves `error` unset.
if payload["count"] == 0:
    print("degraded")
else:
    print("usable")
PY

pass() {
  printf 'ok - %s\n' "$1"
}

warn() {
  printf 'warn - %s\n' "$1" >&2
}

run_pitstop() {
  # shellcheck disable=SC2086
  $pitstop_cmd "$@"
}

assert_json_filter() {
  label="$1"
  file="$2"
  filter="$3"
  if python3 "$tmpdir/assert.py" "$file" "$filter"; then
    pass "$label"
  else
    echo "not ok - $label" >&2
    echo "failed expression: $filter" >&2
    echo "output:" >&2
    sed -n '1,120p' "$file" >&2
    exit 1
  fi
}

assert_output_contains() {
  label="$1"
  file="$2"
  needle="$3"
  if grep -qF -- "$needle" "$file"; then
    pass "$label"
  else
    echo "not ok - $label" >&2
    echo "missing text: $needle" >&2
    echo "output:" >&2
    sed -n '1,120p' "$file" >&2
    exit 1
  fi
}

# The parse guard reads the repo's parser whatever PITSTOP_EVAL_BIN points at:
# the eval files ship with this source tree and must match it.
assert_commands_parse() {
  label="$1"
  file="$2"
  key="$3"
  field="$4"
  if count="$(PYTHONPATH="$repo_root/src" python3 "$tmpdir/parse_commands.py" "$file" "$key" "$field")"; then
    pass "all $count $label parse against the CLI"
  else
    echo "not ok - every $label must parse against the CLI" >&2
    exit 1
  fi
}

json_field() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"
}

task_count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["tasks"]))' "$tasks_file")"
assert_json_filter "loaded $task_count agent eval tasks" "$tasks_file" 'len(d["tasks"]) >= 5 and all(isinstance(t["id"], str) and isinstance(t["prompt"], str) and isinstance(t["expected_command_path"], list) and isinstance(t["pass_criteria"], list) and isinstance(t["common_failures"], list) for t in d["tasks"])'

recipe_count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["recipes"]))' "$recipes_file")"
assert_json_filter "loaded $recipe_count agent recipes" "$recipes_file" 'len(d["recipes"]) >= 5 and all(isinstance(r["id"], str) and isinstance(r["commands"], list) and r["commands"] and isinstance(r["caveats"], list) and r["caveats"] for r in d["recipes"])'

assert_commands_parse "recipe commands" "$recipes_file" recipes commands
assert_commands_parse "task commands" "$tasks_file" tasks expected_command_path

# The checks above need no network. PR CI runs only these, because the live half
# depends on MIMIT and Overpass being up and a contributor cannot act on either.
# The full suite runs in the weekly canary, as it does in odh-cli.
if [ -n "${PITSTOP_EVAL_OFFLINE:-}" ]; then
  printf '\nOffline eval checks passed (file shapes and command parsing).\n'
  exit 0
fi

run_pitstop stations --comune ROMA --fuel Gasolio --cheapest --min-price 1.2 --limit 5 --json >"$tmpdir/cheapest.json"
assert_json_filter "stations --json names MIMIT and both extraction dates" "$tmpdir/cheapest.json" 'd["source"].startswith("MIMIT") and d["source_url"].startswith("https://www.mimit.gov.it/") and is_date(d["registry_extraction_date"]) and is_date(d["price_extraction_date"])'
assert_json_filter "stations --json echoes the query and counts its own stations" "$tmpdir/cheapest.json" 'd["query"]["comune"] == "ROMA" and d["query"]["fuel"] == "Gasolio" and d["query"]["min_price"] == 1.2 and d["count"] == len(d["stations"]) and d["count"] > 0'
assert_json_filter "stations --json timestamps the answer and keeps the not-real-time disclaimer" "$tmpdir/cheapest.json" 'is_iso_utc(d["generated_at"]) and "not real-time" in d["disclaimer"]'
assert_json_filter "every returned price carries median_basis" "$tmpdir/cheapest.json" 'prices(d) and all(p["median_basis"] in ("screened", "unscreened") for p in prices(d))'
assert_json_filter "--cheapest ranks stations by ascending price" "$tmpdir/cheapest.json" 'len(station_min(d)) == d["count"] and station_min(d) == sorted(station_min(d))'
assert_json_filter "--min-price drops every price below the floor" "$tmpdir/cheapest.json" 'all(p["price"] >= 1.2 for p in prices(d))'

run_pitstop stations --comune ROMA --fuel Gasolio --cheapest --min-price 1.2 --drop-outliers --limit 5 --json >"$tmpdir/cheapest-clean.json"
assert_json_filter "--drop-outliers returns no flagged price" "$tmpdir/cheapest-clean.json" 'prices(d) and not any("outlier" in p for p in prices(d))'

# One province, every fuel: the only shape that carries both price classes, since
# a brand-specific fuel is a thin (fuel, provincia) bucket wherever it is sold.
run_pitstop stations --provincia BZ --limit 0 --json >"$tmpdir/province.json"
assert_json_filter "quality counts exactly the prices returned" "$tmpdir/province.json" 'd["quality"]["prices"] == len(prices(d)) and d["quality"]["screened"] + d["quality"]["unscreened"] == d["quality"]["prices"]'
assert_json_filter "quality screened/unscreened split matches each price's median_basis" "$tmpdir/province.json" 'd["quality"]["screened"] == sum(1 for p in prices(d) if p["median_basis"] == "screened") and d["quality"]["unscreened"] == sum(1 for p in prices(d) if p["median_basis"] == "unscreened")'
assert_json_filter "quality outlier count matches the flagged prices" "$tmpdir/province.json" 'd["quality"]["outliers"] == sum(1 for p in prices(d) if p.get("outlier"))'
assert_json_filter "an unscreened price carries no regional_median" "$tmpdir/province.json" 'any(p["median_basis"] == "unscreened" for p in prices(d)) and all("regional_median" not in p and "deviation_pct" not in p for p in prices(d) if p["median_basis"] == "unscreened")'
assert_json_filter "a screened price carries regional_median and deviation_pct" "$tmpdir/province.json" 'any(p["median_basis"] == "screened" for p in prices(d)) and all("regional_median" in p and "deviation_pct" in p for p in prices(d) if p["median_basis"] == "screened")'
assert_json_filter "outlier is present only when true" "$tmpdir/province.json" 'all(p["outlier"] is True for p in prices(d) if "outlier" in p)'

run_pitstop fuels --json >"$tmpdir/fuels.json"
assert_json_filter "fuels --json lists dataset fuel names with row counts" "$tmpdir/fuels.json" 'd["source"].startswith("MIMIT") and is_date(d["price_extraction_date"]) and d["fuels"] and all(f["fuel"].strip() and isinstance(f["count"], int) and f["count"] > 0 for f in d["fuels"])'
assert_json_filter "fuels --json shows ordinary diesel is named Gasolio, not Diesel" "$tmpdir/fuels.json" '"Gasolio" in [f["fuel"] for f in d["fuels"]] and "Diesel" not in [f["fuel"] for f in d["fuels"]]'

run_pitstop stats --fuel Gasolio --json >"$tmpdir/stats.json"
assert_json_filter "stats --json carries source, price date, and generated_at" "$tmpdir/stats.json" 'd["source"].startswith("MIMIT") and is_date(d["price_extraction_date"]) and is_iso_utc(d["generated_at"])'
assert_json_filter "stats --json reports a national baseline per fuel" "$tmpdir/stats.json" 'd["stats"]["Gasolio"]["national"]["count"] > 1000 and d["stats"]["Gasolio"]["national"]["min"] <= d["stats"]["Gasolio"]["national"]["median"] <= d["stats"]["Gasolio"]["national"]["max"]'
assert_json_filter "stats --json reports per-province medians for national coverage" "$tmpdir/stats.json" 'len(d["stats"]["Gasolio"]["provinces"]) >= 80 and all(set(v) == {"median", "min", "max", "count"} and v["min"] <= v["median"] <= v["max"] and v["count"] > 0 for v in d["stats"]["Gasolio"]["provinces"].values())'

run_pitstop stations --comune Bozen --fuel Benzina --limit 5 --geojson >"$tmpdir/stations.geojson"
assert_json_filter "--geojson emits a FeatureCollection with MIMIT provenance" "$tmpdir/stations.geojson" 'd["type"] == "FeatureCollection" and d["metadata"]["source"].startswith("MIMIT") and is_date(d["metadata"]["registry_extraction_date"]) and is_date(d["metadata"]["price_extraction_date"])'
# Italy's longitude band (6..19) and latitude band (35..47.6) do not overlap, so
# a coordinate that satisfies both slots is proof of [lon, lat] order.
assert_json_filter "--geojson geometry is [lon, lat]" "$tmpdir/stations.geojson" 'd["features"] and all(f["geometry"]["type"] == "Point" and 6.0 <= f["geometry"]["coordinates"][0] <= 19.0 and 35.0 <= f["geometry"]["coordinates"][1] <= 47.6 for f in d["features"])'
assert_json_filter "--comune resolves a German municipality name to the MIMIT one" "$tmpdir/stations.geojson" 'd["metadata"]["query"]["comune"] == "BOLZANO"'

run_pitstop stations --comune ROMA --fuel Gasolio --limit 3 >"$tmpdir/stations.txt"
price_date="$(json_field "$tmpdir/cheapest.json" price_extraction_date)"
registry_date="$(json_field "$tmpdir/cheapest.json" registry_extraction_date)"
assert_output_contains "the table path names MIMIT and both extraction dates" "$tmpdir/stations.txt" "Source: MIMIT Osservaprezzi Carburanti (open data) — prices extracted $price_date, registry $registry_date."

# Overpass is a free community endpoint whose transient 5xx is normal operation,
# so it is retried and then downgraded to a warning — the same policy, and the
# same 0/45/120s ladder, as .github/workflows/upstream-smoke.yml. What is never
# downgraded is pitstop's handling of the failure, asserted below on every run.
overpass_state=degraded
attempt=0
for delay in 0 45 120; do
  attempt=$((attempt + 1))
  if [ "$delay" -gt 0 ]; then
    warn "Overpass returned nothing; retrying in ${delay}s (attempt ${attempt}/3)"
    sleep "$delay"
  fi
  if ! run_pitstop chargers --near 46.498,11.354 --radius 8 --fast --limit 5 --json >"$tmpdir/chargers.json"; then
    echo "not ok - chargers exited non-zero, which is a pitstop failure and not an upstream one" >&2
    exit 1
  fi
  overpass_state="$(python3 "$tmpdir/overpass_state.py" "$tmpdir/chargers.json")"
  [ "$overpass_state" = "degraded" ] || break
done

assert_json_filter "chargers --json cites OpenStreetMap and counts its own stations" "$tmpdir/chargers.json" 'd["source"].startswith("OpenStreetMap") and d["source_url"].startswith("https://") and d["count"] == len(d["stations"]) and is_iso_utc(d["generated_at"])'
assert_json_filter "chargers --json reports no per-kWh price" "$tmpdir/chargers.json" '"per-kWh" in d["disclaimer"] and not any(k in s for s in d["stations"] for k in ("price", "price_per_kwh", "tariff", "cost"))'
assert_json_filter "chargers --json blames the upstream only for upstream failures" "$tmpdir/chargers.json" 'overpass_error_is_honest(d)'

if [ "$overpass_state" = "degraded" ]; then
  # An empty answer is allowed to arrive either way: with a populated error
  # (fetch failed, or a remark body) or without one (a valid 200 carrying no
  # elements). Either way the envelope must not invent data.
  assert_json_filter "chargers --json returns an honest empty envelope" "$tmpdir/chargers.json" 'd["count"] == 0 and d["stations"] == [] and (d.get("error") is None or (isinstance(d["error"], str) and d["error"].strip()))'
  warn "Overpass returned no data after ${attempt} attempts; charger data assertions skipped. pitstop's empty envelope was verified. All MIMIT assertions ran."
else
  assert_json_filter "chargers --json returns filtered fast chargers with navigation" "$tmpdir/chargers.json" 'd["count"] > 0 and all(s["max_power_kw"] >= 50 and s["navigation_url"].startswith("https://") and isinstance(s["sockets"], list) for s in d["stations"])'
  assert_json_filter "chargers --json sorts by ascending distance from the query point" "$tmpdir/chargers.json" '[s["distance_km"] for s in d["stations"]] == sorted(s["distance_km"] for s in d["stations"])'
fi

printf '\nAgent eval smoke checks passed. Use evals/agent/tasks.json for manual agent scoring.\n'
