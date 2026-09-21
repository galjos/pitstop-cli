#!/bin/sh
# Geographic acceptance: municipality resolution and charger locations.
#
# Live-only (needs the comuni reference + Overpass). Runs in the weekly
# upstream-smoke workflow, not in PR CI.
#
# Exit 0 -> all location assertions passed, or the upstream was unreachable
#   and that outage was reported honestly (GitHub ::warning, UPSTREAM-* lines).
# Exit 1 -> pitstop resolved a place it should have gotten right. Act on it.
#
# Distance budgets are generous on purpose: they catch a wrong-city regression
# (the 20 km Bolzano reference error this suite exists for) without paging on
# ordinary reference-vs-OSM drift of a few kilometres.

set -u

BIN="${PITSTOP_GEO_BIN:-pitstop}"
OUT="$(mktemp -d "${TMPDIR:-/tmp}/pitstop-geo-acceptance-XXXXXX")"
trap 'rm -rf "$OUT"' EXIT INT TERM

warn() {
  echo "GEO-ACCEPTANCE: UPSTREAM-$1"
}

check_charger_center() {
  name="$1"; comune="$2"; lat="$3"; lon="$4"; budget_km="$5"
  if ! "$BIN" chargers --comune "$comune" --radius 5 --limit 1 --json > "$OUT/center.json" 2>"$OUT/center.err"; then
    if grep -qi "no unique mapped center\|could not fetch\|failed" "$OUT/center.err"; then
      warn "DEGRADED charger center $name unverifiable: $(cat "$OUT/center.err")"
      return 2
    fi
    echo "GEO-ACCEPTANCE: FAIL $name: chargers exited non-zero: $(cat "$OUT/center.err")"
    return 1
  fi
  python3 - "$OUT/center.json" "$name" "$lat" "$lon" "$budget_km" <<'PY'
import json, math, sys

path, name, lat, lon, budget = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
with open(path, encoding="utf-8") as fh:
    payload = json.load(fh)
if payload.get("error"):
    print(f"GEO-ACCEPTANCE: UPSTREAM-DEGRADED charger center {name}: {payload['error']}")
    sys.exit(2)
loc = payload.get("location", {})
try:
    got_lat, got_lon = float(loc["lat"]), float(loc["lon"])
except (KeyError, TypeError, ValueError):
    print(f"GEO-ACCEPTANCE: FAIL {name}: no location in {payload}")
    sys.exit(1)

r = 6371.0
p1, p2 = math.radians(lat), math.radians(got_lat)
h = math.sin(math.radians(got_lat - lat) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(got_lon - lon) / 2) ** 2
km = 2 * r * math.asin(math.sqrt(h))
if km > budget:
    print(f"GEO-ACCEPTANCE: FAIL {name}: center {got_lat},{got_lon} ({km:.1f} km from {lat},{lon}, budget {budget} km)")
    sys.exit(1)
print(f"GEO-ACCEPTANCE: ok {name} center -> {got_lat},{got_lon} ({km:.1f} km)")
PY
}

failures=0
unavailable=0

check_charger_center "Bozen" "Bozen" "46.498" "11.354" "25"; rc=$?
[ "$rc" -eq 1 ] && failures=$((failures + 1))
[ "$rc" -eq 2 ] && unavailable=$((unavailable + 1))

check_charger_center "Roma" "Roma" "41.903" "12.496" "30"; rc=$?
[ "$rc" -eq 1 ] && failures=$((failures + 1))
[ "$rc" -eq 2 ] && unavailable=$((unavailable + 1))

if "$BIN" places Livo --json > "$OUT/livo.json" 2>"$OUT/livo.err"; then
  python3 - "$OUT/livo.json" <<'PY'
import json, sys

with open(sys.argv[1], encoding="utf-8") as fh:
    payload = json.load(fh)
provs = {p.get("provincia") for p in payload.get("places", [])}
if not {"CO", "TN"} <= provs:
    print(f"GEO-ACCEPTANCE: FAIL Livo: CO+TN missing from {sorted(provs)}")
    sys.exit(1)
print("GEO-ACCEPTANCE: ok Livo -> CO+TN both listed")
PY
  [ "$?" -ne 0 ] && failures=$((failures + 1))
  # Ambiguous exact names must refuse to guess (exit 2), not pick a province.
  "$BIN" chargers --comune Livo --json > "$OUT/livo-amb.json" 2>"$OUT/livo-amb.err"
  rc=$?
  if [ "$rc" -eq 2 ] && grep -qi "ambiguous\|disambiguat" "$OUT/livo-amb.err"; then
    echo "GEO-ACCEPTANCE: ok Livo -> ambiguous --comune exits 2"
  else
    echo "GEO-ACCEPTANCE: FAIL Livo: ambiguous --comune exited $rc, want 2 with a disambiguation error: $(cat "$OUT/livo-amb.err")"
    failures=$((failures + 1))
  fi
else
  warn "UNAVAILABLE places Livo exited non-zero: $(cat "$OUT/livo.err")"
  unavailable=$((unavailable + 1))
fi

if "$BIN" chargers --near 46.498,11.354 --radius 5 --limit 5 --json > "$OUT/chargers.json" 2>"$OUT/chargers.err"; then
  python3 - "$OUT/chargers.json" <<'PY'
import json, math, sys

with open(sys.argv[1], encoding="utf-8") as fh:
    payload = json.load(fh)
if payload.get("error"):
    print(f"GEO-ACCEPTANCE: UPSTREAM-DEGRADED chargers: {payload['error']}")
    sys.exit(2)
qlat, qlon, radius = 46.498, 11.354, 5.0
for st in payload.get("stations", []):
    try:
        d = float(st.get("distance_km", "nan"))
    except (TypeError, ValueError):
        print(f"GEO-ACCEPTANCE: FAIL charger without distance: {st.get('name')}")
        sys.exit(1)
    if not (d <= radius + 1.0):
        print(f"GEO-ACCEPTANCE: FAIL charger {st.get('name')} at {d} km, outside radius {radius} km + 1 km tolerance")
        sys.exit(1)
print(f"GEO-ACCEPTANCE: ok chargers near 46.498,11.354 ({payload.get('count', 0)} returned)")
PY
  rc=$?
  [ "$rc" -eq 1 ] && failures=$((failures + 1))
  [ "$rc" -eq 2 ] && unavailable=$((unavailable + 1))
else
  warn "UNAVAILABLE chargers exited non-zero: $(cat "$OUT/chargers.err")"
  unavailable=$((unavailable + 1))
fi

if [ "$failures" -gt 0 ]; then
  echo "GEO-ACCEPTANCE: $failures failing check(s)"
  exit 1
fi
if [ "$unavailable" -gt 0 ]; then
  echo "::warning title=Geo acceptance skipped on unreachable upstream::$unavailable check(s) could not reach the comuni reference or Overpass; location assertions that ran passed."
fi
echo "GEO-ACCEPTANCE: passed"
