# pitstop

`pitstop` is an unofficial, JSON-first command-line tool for **Italian fuel-station prices**, backed by the public **MIMIT _Osservaprezzi Carburanti_** open data. It is built for agents, scripts, and humans that want a stable, deterministic answer to questions like "cheapest diesel near here" instead of scraping a web UI.

It downloads the official station registry and daily price file, joins them locally, and exposes filter/sort/proximity queries with a compact table or machine-readable JSON.

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

Run without installing (with [uv](https://docs.astral.sh/uv/)):

```bash
uvx --from . pitstop stations --comune ROMA --fuel Gasolio --cheapest
```

Install as a tool:

```bash
uv tool install .       # or: pipx install .
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

`stations` flags: `--comune`, `--provincia`, `--brand`, `--near "lat,lon"`, `--radius`, `--fuel` (substring, case-insensitive), `--self`, `--served`, `--cheapest` (needs `--fuel`), `--min-price` (drop values below a floor; e.g. `1.2` to skip placeholders), `--fresh-within-days` (drop stale prices), `--max-deviation-pct` (drop prices more than N% below their fuel's provincial median — catches misreports), `--no-comune-validate`, `--limit`, `--json`. Loading flags (`--refresh`, `--max-age`, `--timeout`) apply to any data command.

Every returned price carries `regional_median`, `deviation_pct`, and an `outlier` flag (true when >15% below the local median **or** below the Tukey lower fence Q1−1.5·IQR — the Tukey rule catches misreports in tight markets that the percent rule alone misses). Pass `--drop-outliers` to remove flagged prices entirely.

## MCP server

For agents that speak MCP, the same data is exposed as tools (`list_fuels`, `find_stations`, `find_cheapest`) over the shared core:

```bash
pip install "pitstop[mcp]"   # or: uv tool install "pitstop[mcp]"
pitstop-mcp                  # stdio MCP server
```

Example client config entry:

```json
{ "mcpServers": { "pitstop": { "command": "pitstop-mcp" } } }
```

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

## Automation contract

- `stdout` is command output; `stderr` is diagnostics.
- `--json` emits a stable object with `source`, `*_extraction_date`, `generated_at`, `query`, `count`, `stations[]`, and `disclaimer`.
- Exit codes: `0` success, `1` runtime error, `2` usage error.
- Source files are cached (default 24h) under `$XDG_CACHE_HOME/pitstop`; use `--refresh` to bypass.
- Non-interactive; no hidden browser state or scraping.

## Status & roadmap

v0.7.0 — fuel-price core (registry+price join, filters, proximity, cheapest, `--min-price` floor, `--fresh-within-days` freshness, combined 15% + Tukey IQR outlier rule, ISTAT comune-coordinate validation, JSON) + **EV charging stations via OSM Overpass** (operator, plug types, max kW, fee, access — `pitstop chargers`). MCP server, Claude skill, tests, CI.

Planned, roughly in order:
- **EV charging** (locations via Open Charge Map; prices via the AFIR National Access Point / DATEX II as that data matures);
- additional countries behind a per-country source adapter (e.g. Germany Tankerkönig, France/Spain official feeds).

## Data sources & attributions

- Fuel stations and prices: **MIMIT Osservaprezzi Carburanti** open data.
- Comune coordinates (validation): **opendatasicilia/comuni-italiani** (ISTAT-derived).
- EV charging stations: **OpenStreetMap** via the Overpass API (© OpenStreetMap contributors, ODbL).

## Links

- MIMIT fuel open data: https://www.mimit.gov.it/it/open-data/elenco-dataset/carburanti-prezzi-praticati-e-anagrafica-degli-impianti
