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
  - Some stations are **mis-geocoded** in the registry. v0.3.0 annotates stations >30 km from their comune's median (or outside Italy) as `coordinate_suspect` (`*` in the table), and `--near` skips coordinates outside the Italy bounding box. Single-station comuni cannot be validated this way and need a second source (planned).

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
```

`stations` flags: `--comune`, `--provincia`, `--brand`, `--near "lat,lon"`, `--radius`, `--fuel` (substring, case-insensitive), `--self`, `--served`, `--cheapest` (needs `--fuel`), `--min-price` (drop values below a floor; e.g. `1.2` to skip placeholders), `--fresh-within-days` (drop prices last updated more than N days ago), `--limit`, `--json`. Loading flags (`--refresh`, `--max-age`, `--timeout`) apply to any data command.

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

v0.3.0 — fuel-price core (registry+price join, filters, proximity, cheapest, `--min-price` floor, `--fresh-within-days` freshness filter, `coordinate_suspect` geocoding signal, JSON), an MCP server, a Claude skill, tests, and CI.

Planned, roughly in order:
- a **second data source** of Italian comune coordinates (e.g. ISTAT) to validate single-station-comune coordinates that the self-contained method can't reach;
- **EV charging** (locations via Open Charge Map; prices via the AFIR National Access Point / DATEX II as that data matures);
- additional countries behind a per-country source adapter (e.g. Germany Tankerkönig, France/Spain official feeds).

## Links

- MIMIT fuel open data: https://www.mimit.gov.it/it/open-data/elenco-dataset/carburanti-prezzi-praticati-e-anagrafica-degli-impianti
