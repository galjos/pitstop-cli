---
name: pitstop
description: Look up Italian fuel-station prices (petrol, diesel, GPL, methane, HVO) by municipality, province, brand, or proximity to a coordinate, and find the cheapest. Backed by MIMIT Osservaprezzi Carburanti official open data. Use for questions like "cheapest diesel near X in Italy" or "fuel stations in <comune>".
---

# pitstop

`pitstop` answers Italian fuel-price questions from official MIMIT open data. It downloads and caches the national station registry + daily price file and joins them locally, so you get a small JSON answer instead of multi-megabyte CSVs.

## When to use

- "Cheapest diesel / petrol near <place or coordinate> in Italy"
- "Fuel stations in <comune/province>" and their prices
- Comparing self-service vs served prices, or brands, for Italian stations

Do **not** use for: live/intraday prices (this is daily data), EV charging, or countries other than Italy.

## Commands

Always pass `--json` when consuming the output programmatically.

```bash
# Cheapest of a fuel in a municipality (--cheapest requires --fuel)
# Add --min-price 1.2 to skip placeholders and --fresh-within-days 90 to skip stale prices.
pitstop stations --comune ROMA --fuel Gasolio --cheapest --min-price 1.2 --fresh-within-days 90 --limit 5 --json

# Nearest stations to a coordinate, self-service petrol within 5 km
pitstop stations --near 46.498,11.354 --radius 5 --fuel Benzina --self --json

# Discover valid fuel-type names before filtering
pitstop fuels --json
```

Key flags: `--comune`, `--provincia` (2-letter, e.g. `BZ`), `--brand`, `--near "lat,lon"` + `--radius` (km), `--fuel` (substring, case-insensitive), `--self` / `--served`, `--cheapest`, `--min-price` (price floor), `--fresh-within-days` (drop stale prices), `--limit`, `--json`. The MCP `find_cheapest` tool applies a fuel-aware floor and a 90-day freshness window by default.

If your client speaks MCP instead of shelling out, the same capabilities are available as MCP tools (`list_fuels`, `find_stations`, `find_cheapest`) via `pitstop-mcp` (install `pitstop[mcp]`).

## JSON contract

`stations --json` returns: `source`, `source_url`, `registry_extraction_date`, `price_extraction_date`, `generated_at`, `query`, `count`, `stations[]`, `disclaimer`. Each station has `id, operator, brand, type, name, address, comune, provincia, lat, lon, prices[]` (and `distance_km` when `--near` is used). Each price has `fuel, price, self_service, updated`.

Exit codes: `0` ok, `1` runtime error (e.g. network), `2` usage error.

## Caveats to surface to the user

- **Daily, not real-time** — prices are as of ~08:00 the day before `price_extraction_date`. State this when answering.
- **`--fuel` is a substring match** — `Gasolio` also matches `Gasolio Premium`, `Gasolio Oro Diesel`, etc. Use `pitstop fuels` to pick exact names; inspect the `fuel` field in results.
- **Placeholder prices** — some operators report junk values like `1.000`; with `--cheapest` these can rank first. Pass `--min-price 1.2` (petrol/diesel) to drop them; use a lower floor for cheaper fuels like GPL. Still sanity-check the lowest result.
- **Stale prices** — some records were last updated years ago and may be far below the current market. Pass `--fresh-within-days 90` and check the `updated` field before reporting a price as current.
- **Mis-geocoded stations** — a few registry coordinates are wrong. Results carry a `coordinate_suspect: true` flag (table marker `*`) when a station is far from its comune's other stations or outside Italy. When you see it, treat the result as low-confidence and double-check the `comune`/`address`. **Single-station comuni cannot be flagged** with the current method, so for `--near` results in remote/small comuni, always sanity-check the comune name against the user's query.
