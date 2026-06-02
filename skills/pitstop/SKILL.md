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
- Finding EV chargers near a coordinate or municipality (OSM)

Do **not** use the *fuel* commands for: live/intraday prices (this is daily data) or countries other than Italy. **For EV charging**, use `pitstop chargers` / MCP `find_chargers` — separate domain backed by OpenStreetMap. **Per-station €/kWh tariffs are NOT in open data in Italy**; each charger result includes a `tariff_info_url` linking to the operator's official tariff page — surface that to the user instead of guessing a price.

## Commands

Always pass `--json` when consuming the output programmatically, or `--geojson` if you have mapping/GIS capabilities.

```bash
# Multi-fuel query in a municipality (supports EN/FR/DE city names)
pitstop stations --comune Milan --fuel "Benzina,Gasolio" --cheapest --limit 5 --json

# Nearest stations to a coordinate, with navigation URLs
pitstop stations --near 46.498,11.354 --radius 5 --fuel Benzina --json

# Export to GeoJSON FeatureCollection
pitstop stations --comune ROME --fuel Gasolio --geojson

# Find EV chargers with error reporting
pitstop chargers --comune Venice --json
```

Key flags:
- `--comune`: Municipality name. Supports international names (**Rome, Milan, Venice, Florence, Bozen, Mailand, Venise**, etc.).
- `--fuel`: Substring search. Supports **comma-separated lists** (e.g. `Benzina,Gasolio`).
- `--geojson`: Emits a standard GeoJSON FeatureCollection with properties and geometry.
- Other flags: `--provincia`, `--brand`, `--near`, `--radius`, `--self`/`--served`, `--cheapest`, `--min-price`, `--fresh-within-days`, `--limit`, `--json`.

## JSON / GeoJSON contract

- `stations --json` returns a stable envelope with `stations[]` and `query`. Each station includes a `navigation_url` (Google Maps).
- `stations --geojson` returns a `FeatureCollection`. Geometry is `Point` [lon, lat]. Properties include all station metadata.
- `chargers` output includes an `error` field in the envelope when the external Overpass API fails.

## Advice for Agents

- **Use International Names:** You can pass "Rome" or "Milan" directly to `--comune`; the tool handles the translation to the Italian dataset keys.
- **Batch Fuel Queries:** To compare Petrol and Diesel, use `--fuel "Benzina,Gasolio"` in a single call.
- **Surface Maps:** Always include the `navigation_url` in your response so the user can navigate to the station immediately.
- **Handle Outliers:** Every price carries `regional_median`, `deviation_pct`, and an `outlier` flag (true when >15% below the local median). Use this to warn users about potential data errors in the open feed.
- **Check suspect coordinates:** A `coordinate_suspect: true` flag appears when a station's coord is far from its declared comune's centroid. Treat these with low confidence.
