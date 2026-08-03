# pitstop

[![CI](https://github.com/galjos/pitstop-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/galjos/pitstop-cli/actions/workflows/ci.yml)
[![Release](https://github.com/galjos/pitstop-cli/actions/workflows/release.yml/badge.svg)](https://github.com/galjos/pitstop-cli/actions/workflows/release.yml)
[![Upstream smoke](https://github.com/galjos/pitstop-cli/actions/workflows/upstream-smoke.yml/badge.svg)](https://github.com/galjos/pitstop-cli/actions/workflows/upstream-smoke.yml)

A JSON-first CLI and MCP server for **Italian fuel-station prices** and **EV charging stations**, designed for AI agents, scripts, and humans.

Italy publishes per-station fuel prices daily (MIMIT *Osservaprezzi Carburanti* open data) and OpenStreetMap maps every EV charger in the country, but raw access means downloading multi-megabyte CSVs, joining files, sorting through misreports, and translating between Italian comune names and the ones a user actually types. `pitstop` does all of that locally and returns a small, well-formed JSON envelope.

Built for questions like:
- *"What's the cheapest diesel near Rome right now?"* → `pitstop stations --fuel Gasolio --near 41.9,12.5 --cheapest`
- *"Where can I fast-charge my EV in Bolzano?"* → `pitstop chargers --comune Bozen --fast`
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
  - Some price records are **stale** (a few were last updated years ago); use `--fresh-within-days` and check the `UPDATED` column / `updated` field.
  - Some stations are **mis-geocoded** in the registry. As of v0.4.0 `pitstop` joins a second data source (ISTAT-derived comune coordinates from [opendatasicilia/comuni-italiani](https://github.com/opendatasicilia/comuni-italiani), 97.5% match) to validate each station's coordinate against its declared comune's *true* location. Stations >30 km off are flagged `coordinate_suspect` (`*` in the table), and `--near` excludes stations whose declared comune is geographically too far from the query point — even single-station comuni like RASUN-ANTERSELVA. Pass `--no-comune-validate` to disable.

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
pitstop chargers --near 46.498,11.354 --radius 5 --fast --json
```

`stations` flags: `--comune`, `--provincia`, `--brand`, `--near "lat,lon"`, `--radius`, `--fuel` (substring, case-insensitive), `--self`, `--served`, `--cheapest` (needs `--fuel`), `--min-price` (drop values below a floor; e.g. `1.2` to skip placeholders), `--fresh-within-days` (drop stale prices), `--max-deviation-pct` (drop prices more than N% below their fuel's provincial median — catches misreports), `--no-comune-validate`, `--limit`, `--json`. Loading flags (`--refresh`, `--max-age`, `--timeout`) apply to the MIMIT data commands (`stations`, `fuels`, `stats`); `chargers` uses its own OSM cache and takes only `--refresh`.

Every returned price carries a `median_basis`. A `screened` price also carries `regional_median` and `deviation_pct`, plus `outlier: true` when it is >15% below the local median **or** below the Tukey lower fence Q1−1.5·IQR (the Tukey rule catches misreports in tight markets that the percent rule alone misses). The `outlier` key is emitted **only when it is true**, so read it as optional. Pass `--drop-outliers` to remove flagged prices entirely.

A price is `unscreened` when its (fuel, provincia) bucket holds too few samples for a median, so **no outlier check ran on it** and it is returned as reported (the table marks these `~`). The `--json` envelope's `quality` block counts screened vs unscreened prices for the answer you got.

## MCP server

For agents that speak MCP, the same data is exposed as tools (`list_fuels`, `find_stations`, `find_cheapest`, `find_chargers`, `get_stats`) over the shared core:

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
```

## Automation contract

- `stdout` is command output; `stderr` is diagnostics.
- `--json` emits a stable object with `source`, `*_extraction_date`, `generated_at`, `query`, `count`, `quality`, `stations[]`, and `disclaimer`.
- Exit codes: `0` success, `1` runtime error, `2` usage error.
- Source files are cached (default 24h) under `$XDG_CACHE_HOME/pitstop`; use `--refresh` to bypass.
- Non-interactive; no hidden browser state or scraping.

## Status & roadmap

v1.1.0 — stable public release: fuel-price core (registry+price join, filters, proximity, cheapest, `--min-price` floor, `--fresh-within-days` freshness, combined 15% + Tukey IQR outlier rule, ISTAT comune-coordinate validation, JSON) + **EV charging stations via OSM Overpass** (operator, plug types, max kW, fee, access — `pitstop chargers`) + **operator tariff-page URLs** attached to each EV result. Includes **multi-fuel query support**, **international municipality mapping** (EN/FR/DE), **macro price statistics** (`pitstop stats`), and **navigation/GeoJSON support**. MCP server, agent skill, tests, CI.

Planned, roughly in order:
- per-station **EV tariff data** if a source `pitstop` can read starts publishing per-kWh prices (today it parses only OSM's `fee` yes/no flag, no price field);
- additional countries behind a per-country source adapter, only where the source's own terms permit the bulk download and locally derived ranking `pitstop` does.

## Data sources & attributions

- Fuel stations and prices: **MIMIT Osservaprezzi Carburanti** open data.
- Comune coordinates (validation): **opendatasicilia/comuni-italiani** (ISTAT-derived).
- EV charging stations: **OpenStreetMap** via the Overpass API (© OpenStreetMap contributors, ODbL).

## Links

- MIMIT fuel open data: https://www.mimit.gov.it/it/open-data/elenco-dataset/carburanti-prezzi-praticati-e-anagrafica-degli-impianti
