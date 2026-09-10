# pitstop

[![CI](https://github.com/galjos/pitstop-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/galjos/pitstop-cli/actions/workflows/ci.yml)
[![Release](https://github.com/galjos/pitstop-cli/actions/workflows/release.yml/badge.svg)](https://github.com/galjos/pitstop-cli/actions/workflows/release.yml)
[![Upstream smoke](https://github.com/galjos/pitstop-cli/actions/workflows/upstream-smoke.yml/badge.svg)](https://github.com/galjos/pitstop-cli/actions/workflows/upstream-smoke.yml)

A JSON-first CLI and MCP server for **Italian fuel-station prices** and **EV charging stations**, designed for AI agents, scripts, and humans.

Italy publishes per-station fuel prices daily (MIMIT *Osservaprezzi Carburanti* open data), and OpenStreetMap provides EV charger locations and capabilities. Raw access means downloading multi-megabyte CSVs, joining files, sorting through misreports, and translating municipality names. `pitstop` handles those steps locally and returns JSON or a readable table.

Built for questions like:
- *"What's the cheapest diesel near Rome right now?"* → `pitstop stations --fuel Gasolio --near 41.9,12.5 --cheapest`
- *"Where can I fast-charge my EV in Bolzano?"* → `pitstop chargers --near 46.498,11.354 --fast`
- *"Are these station prices statistically reliable?"* → every price says whether it was screened against its local market; screened ones carry a `regional_median`, a `deviation_pct`, and `outlier: true` when the price looks like a misreport.

International city names work out of the box (`Rome`, `Milan`, `Bozen`, `Mailand`, `Venise`, …).

## Disclaimer

Unofficial community project. Not affiliated with or endorsed by MIMIT. Fuel data belongs to MIMIT and is redistributed here under its open-data terms; `pitstop` always emits source and extraction-date provenance in its output.

## Data scope & freshness

- **Source:** MIMIT _Osservaprezzi Carburanti_ open data — a station registry (`anagrafica`, ~23.8k active stations) and a daily practiced-price file, joined on `idImpianto`.
- **Freshness:** prices reflect values reported by operators **as of ~08:00 the day before** the published extraction date. This is **daily, not real-time.**
- **Coverage:** Italy only (by design, for now).
- **Known caveats:**
  - Some operators report placeholder values (e.g. `1.000`); use `--min-price` (e.g. `1.2`) to drop them.
  - Some price records are **stale** (a few were last updated years ago); use `--fresh-within-days` and check the `UPDATED` column / `updated` field. When enabled, the freshness filter also excludes missing, unparseable, and future update dates.
  - Some stations are **mis-geocoded** in the registry. `pitstop` uses station clusters and a second coordinate reference from [opendatasicilia/comuni-italiani](https://github.com/opendatasicilia/comuni-italiani) to flag discrepancies over 30 km as `coordinate_suspect` (`*` in the table). `--near` also excludes stations whose declared comune is geographically too far from the query point. Pass `--no-comune-validate` to disable the second reference.
  - **Municipality reference coordinates can also be wrong.** Charger searches resolve a municipality's ISTAT ID to its mapped OpenStreetMap administrative center. JSON includes the selected `location`, its source link, cache age, and warnings when it differs from the reference coordinates. Ambiguous names require `--provincia` or `--comune-id`. If no mapped center is available, supply `--near lat,lon`.

## Install

Requires Python ≥ 3.10. No third-party runtime dependencies.

From PyPI (the package is published as **`pitstop-cli`**; the CLI binary is `pitstop`):

```bash
pipx install pitstop-cli           # or
uv tool install pitstop-cli        # or just run on-demand:
uvx --from pitstop-cli pitstop --help
```

For the MCP server (optional extra):

```bash
pipx install "pitstop-cli[mcp]"
pitstop-mcp                        # stdio MCP server
```

Run from a source checkout during development:

```bash
PYTHONPATH=src python3 -m pitstop --help
```

## Usage

```bash
# Cheapest *fresh* diesel in a municipality (skip placeholder + stale prices)
pitstop stations --comune ROMA --fuel Gasolio --cheapest --min-price 1.2 --fresh-within-days 90 --limit 5

# Self-service petrol within 5 km of a coordinate, as JSON
pitstop stations --near 46.498,11.354 --radius 5 --fuel Benzina --self --json

# Discover the fuel-type names present in the data
pitstop fuels

# Fast EV chargers (≥50 kW) within 5 km of Bolzano
pitstop chargers --comune Bozen --radius 5 --fast --public --json

# Discover municipality IDs and disambiguate duplicate names
pitstop places Livo --json
pitstop chargers --comune Livo --provincia TN --json
pitstop chargers --comune-id 021008 --radius 5 --fast --json
```

`stations` flags: `--comune`, `--provincia`, `--brand`, `--near "lat,lon"`, `--radius`, `--fuel` (substring, case-insensitive), `--self`, `--served`, `--cheapest` (needs `--fuel`), `--min-price`, `--fresh-within-days`, `--max-deviation-pct`, `--no-comune-validate`, `--limit`, `--json`, `--geojson`. Choose one output format. `--limit 0` returns every match.

Distances and radii are straight-line measurements, not driving distances or travel times.

Loading flags (`--refresh`, `--max-age` in seconds, `--timeout` in seconds) apply to MIMIT commands and charger searches. The default caches last 24 hours for MIMIT, seven days for OSM, and 30 days for the municipality reference. `--refresh` also refreshes a charger's municipality lookup; `--max-age` controls its charger results. `--max-age 0` accepts cached files of any age. `places` supports `--refresh` and `--timeout`.

Every returned price carries a `median_basis`. A `screened` price also carries `regional_median` and `deviation_pct`, plus `outlier: true` when it is >15% below the local median **or** below the Tukey lower fence Q1−1.5·IQR (the Tukey rule catches misreports in tight markets that the percent rule alone misses). The `outlier` key is emitted **only when it is true**, so read it as optional. Pass `--drop-outliers` to remove flagged prices entirely.

A price is `unscreened` when its (fuel, provincia) bucket holds too few samples for a median, so **no outlier check ran on it** and it is returned as reported (the table marks these `~`). The `--json` envelope's `quality` block counts screened vs unscreened prices for the answer you got.

## MCP server

For agents that speak MCP, the same data is exposed as six tools (`list_fuels`, `find_stations`, `find_cheapest`, `find_chargers`, `find_places`, `get_stats`) over the shared core. Tools advertise read-only behavior and return structured JSON alongside text. Repeated fuel searches reuse parsed files and provincial statistics until the cached files change.

```bash
pip install "pitstop-cli[mcp]"   # or: uv tool install "pitstop-cli[mcp]"
pitstop-mcp                      # stdio MCP server
```

Example client config entry:

```json
{ "mcpServers": { "pitstop": { "command": "pitstop-mcp" } } }
```

Machine-readable command recipes, with the caveats that belong with each answer, are in [evals/agent/recipes.json](evals/agent/recipes.json); the agent skill bundle is in [skills/pitstop/SKILL.md](skills/pitstop/SKILL.md). `scripts/run-agent-evals.sh` checks those recipes against the live CLI, and [evals/agent/README.md](evals/agent/README.md) explains how a scored round is recorded.

## Development

```bash
pip install -e ".[dev]"
pytest -q
python scripts/smoke-installed.py  # installed entry points and stdio MCP, offline
```

## Automation contract

- `stdout` is command output; `stderr` is diagnostics.
- `stations --json` emits a stable object with `source`, `*_extraction_date`, `generated_at`, `query`, `count`, `quality`, `stations[]`, and `disclaimer`.
- Fuel and charger search envelopes include `coverage`: `fetched_count`, `matched_count` before the limit, `returned_count`, and `truncated`. These counts describe the downloaded data; OSM coverage is not an exhaustive charger inventory.
- `freshness` records local `fetched_at` and `age_seconds`: separately for the fuel registry and prices, or for the charger response. Charger `cache_status` is `hit`, `miss`, `stale_fallback`, `partial`, or `unavailable`. A partial/unavailable response has no successful fetch timestamp; an `error` explains degraded results. Fetch time does not establish current prices or charger availability.
- Charger municipality searches add `location` with the selected name, province, ISTAT ID, coordinates, provenance, and warnings. GeoJSON carries these envelope fields under `metadata`.
- Exit codes: `0` success, `1` runtime error, `2` usage error.
- Source files are cached under `$XDG_CACHE_HOME/pitstop` (or `~/.cache/pitstop`); use `--refresh` to bypass.
- Non-interactive; no hidden browser state or scraping.

## Status & roadmap

v1.2.0 adds municipality discovery, province and ISTAT-ID selection for chargers, search coverage and cache timestamps, and structured MCP results. Fuel prices, EV charger locations, statistics, navigation links, and GeoJSON remain available through the CLI and MCP server. See [CHANGELOG.md](CHANGELOG.md) for fixes and compatibility details.

Planned, roughly in order:
- per-station **EV tariff data** if a source `pitstop` can read starts publishing per-kWh prices (today it parses only OSM's `fee` yes/no flag, no price field);
- additional countries behind a per-country source adapter, only where the source's own terms permit the bulk download and locally derived ranking `pitstop` does.

## Data sources & attributions

- Fuel stations and prices: **MIMIT Osservaprezzi Carburanti** open data.
- Comune coordinates (validation): **opendatasicilia/comuni-italiani** (ISTAT-derived).
- EV charging stations: **OpenStreetMap** via the Overpass API (© OpenStreetMap contributors, ODbL).

## Links

- MIMIT fuel open data: https://www.mimit.gov.it/it/open-data/elenco-dataset/carburanti-prezzi-praticati-e-anagrafica-degli-impianti
