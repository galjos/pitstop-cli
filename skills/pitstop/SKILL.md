---
name: pitstop
description: Italian fuel-station prices (petrol, diesel, GPL, methane, HVO) and EV charging stations. Find cheapest by municipality / province / brand / coordinate, look up EV chargers near a place, get macro price stats. Backed by MIMIT Osservaprezzi Carburanti, OpenStreetMap (Overpass), and ISTAT comune coordinates. Use for "cheapest diesel near X in Italy", "fuel stations in <comune>", or "EV chargers near <comune>".
homepage: https://github.com/galjos/pitstop-cli
metadata:
  {
    "openclaw":
      {
        "os": ["darwin", "linux"],
        "requires": { "bins": ["pitstop"] },
        "install":
          [
            {
              "id": "uvx",
              "kind": "uvx",
              "package": "pitstop-cli>=1.1.0",
              "bins": ["pitstop"],
              "label": "Run pitstop on demand (uvx)",
            },
            {
              "id": "pipx",
              "kind": "pipx",
              "package": "pitstop-cli>=1.1.0",
              "bins": ["pitstop"],
              "label": "Install pitstop (pipx)",
            },
          ],
      },
  }
---

# pitstop

`pitstop` answers Italian fuel-price questions from official MIMIT open data. It downloads and caches the national station registry + daily price file and joins them locally, so you get a small JSON answer instead of multi-megabyte CSVs.

## When to use

- "Cheapest diesel / petrol near <place or coordinate> in Italy"
- "Fuel stations in <comune/province>" and their prices
- Comparing self-service vs served prices, or brands, for Italian stations
- Finding EV chargers near a coordinate or municipality (OSM)

Do **not** use the *fuel* commands for: live/intraday prices (this is daily data) or countries other than Italy. **For EV charging**, use `pitstop chargers` / MCP `find_chargers` — separate domain backed by OpenStreetMap. **Per-station €/kWh tariffs are never returned by `pitstop chargers` / MCP `find_chargers`** (it parses OSM's `fee` yes/no flag and no price field); each charger result includes a `tariff_info_url` linking to the operator's official tariff page — surface that to the user instead of guessing a price.

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

- `stations --json` returns a stable envelope with `stations[]`, `query`, and a `quality` block (how many returned prices were screened against a local median). Each station includes a `navigation_url` (Google Maps).
- `stations --geojson` returns a `FeatureCollection`. Geometry is `Point` [lon, lat]. Properties include all station metadata.
- `chargers` output includes an `error` field in the envelope when the external Overpass API fails.

## Advice for Agents

- **Use International Names:** You can pass "Rome" or "Milan" directly to `--comune`; the tool handles the translation to the Italian dataset keys.
- **Batch Fuel Queries:** To compare Petrol and Diesel, use `--fuel "Benzina,Gasolio"` in a single call.
- **Surface Maps:** Always include the `navigation_url` in your response so the user can navigate to the station immediately.
- **Handle Outliers:** Every price carries a `median_basis`. A `screened` price also carries `regional_median` and `deviation_pct`, plus `outlier: true` when it is >15% below the local median **or** below the Tukey lower fence Q1−1.5·IQR. The `outlier` key is present **only when it is true**, so read it as optional (`price.get("outlier")`, not `price["outlier"]`). Use the flag to warn users about potential data errors in the open feed.
- **Don't over-trust `unscreened` prices:** an `unscreened` price sits in a (fuel, provincia) bucket with too few samples to compute a median, so **no outlier check ran on it** — it is returned exactly as reported. The envelope's `quality` block counts `screened` vs `unscreened` for the answer you actually got — don't assume a fixed share — so check it before calling a suspiciously cheap price a bargain.
- **Check suspect coordinates:** A `coordinate_suspect: true` flag appears when a station's coord is far from its declared comune's centroid. Treat these with low confidence.

Machine-readable versions of these command patterns, each with the caveats that must travel with the answer, are in `evals/agent/recipes.json` in the repo.
