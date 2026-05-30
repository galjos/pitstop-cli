# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-05-30

### Added
- **Price-outlier detection.** Every price is annotated with `regional_median`
  and `deviation_pct` against the median for its (fuel, provincia) — computed
  from the dataset itself, no extra source. Prices more than 15% below their
  regional median get an `outlier: true` flag. The CLI table marks outliers
  with `?` and prints a footnote.
- `--max-deviation-pct N` on `pitstop stations` (and `max_deviation_pct` on the
  MCP tools) to drop prices that fall too far below the local market — opt-in,
  off by default to preserve fidelity.

### Why
Empirically, Q8 Verona at €1.638 (vs €2.06 VR-Gasolio median, −20.4%) and
ENI Rome at €1.639 (vs €2.07 RM-Gasolio median, −20.8%) are statistical
outliers — likely misreports. The signal cleanly separates them from real
discount stations (whose prices are typically ~5–7% below median).

## [0.4.0] - 2026-05-30

### Added
- **Second data source: Italian comune coordinates.** New `geocoding.py` module
  fetches and caches an ISTAT-derived comune→(lat, lon) reference
  (opendatasicilia/comuni-italiani) with 30-day cache and graceful fallback if
  the upstream is unreachable. Achieves 97.5% comune-name match against MIMIT.
- Comune validation in `query_stations`:
  - flags `coordinate_suspect` when a station's stored coord is more than 30 km
    from its declared comune's **true** location — this catches single-station
    comuni (the original Rasen case) that the self-contained centroid method
    provably could not.
  - in `--near`, also excludes stations whose declared comune is outside
    `radius_km + 30 km` of the query point; "Agip Tankstelle Rasen" no longer
    appears in `--near 46.498,11.354 --radius 6`.
- `--no-comune-validate` flag to skip the second source (offline/perf).

### Known limitations
- 2.5% of MIMIT comune strings don't match the reference (mostly garbage in the
  comune field, recent comune mergers, minor spelling). The self-contained
  centroid heuristic still applies to those.
- The upstream comune dataset has no explicit LICENSE in its repo, though the
  underlying data is ISTAT-derived. `pitstop` runtime-fetches only and credits
  the source — if pitstop ever goes public, prefer a Wikidata-bundled file.

## [0.3.0] - 2026-05-29

### Added
- `coordinate_suspect` flag on stations whose registry coordinate is outside the
  Italy bounding box **or** more than 30 km from the median of their comune's
  other stations. Flags ~1% of stations (211/23.8k). Surfaced in JSON output and
  marked with `*` in the table. Advisory — not filtered by default.
- `--near` skips stations whose coordinates fall outside the Italy bounding box.

### Known limitations
- Single-station comuni (e.g. RASUN-ANTERSELVA, the original Rasen example)
  **cannot** be validated by the comune-cluster method — there is no sibling
  station to compare against. The robust fix for this class requires a second
  data source such as an ISTAT comune-coordinates reference. Tracked as the next
  step.
- A few comuni span large or split geographies (island groups, archipelagos), so
  some flagged outliers are legitimately distant rather than mis-geocoded.

## [0.2.0] - 2026-05-29

### Added
- **Price freshness filtering.** `--fresh-within-days N` on `pitstop stations`
  (and `max_age_days` on the MCP tools) drops prices whose `updated` timestamp is
  older than N days. MCP `find_cheapest` defaults to 90 days so stale records
  cannot win "cheapest".
- `UPDATED` column in the `pitstop stations` table so price recency is visible.

### Fixed
- A stale record could rank as cheapest: a 2023 "Gasolio Alpino" at €1.749 was
  returned as the cheapest diesel near Bolzano even though that station's current
  diesel is €2.115 (national self-service average ~€2.03 on 2026-05-29). The
  freshness filter resolves this.

### Known limitations
- Some stations are mis-geocoded in the registry (e.g. a Val Pusteria station
  placed ~5 km from Bolzano), so proximity results can include far-away stations.
  Check each result's `comune`/`address`.

## [0.1.1] - 2026-05-29

### Fixed
- MCP `find_cheapest` now applies a **fuel-aware** default price floor instead of
  a fixed `1.2`. The old default silently returned no results for cheaper fuels
  like GPL (~€0.77). Petrol/diesel/methane keep the `1.2` placeholder floor; GPL
  gets none. Pass `min_price >= 0` to override. Surfaced by an agent simulation.

## [0.1.0] - 2026-05-29

### Added
- `--min-price` floor on `pitstop stations` to drop placeholder/junk prices
  (e.g. `1.000`) that otherwise pollute `--cheapest`.
- **MCP server** (`pitstop-mcp`, optional `[mcp]` extra) exposing `list_fuels`,
  `find_stations`, and `find_cheapest` over the same core as agent tools.
- pytest test suite covering parsing, the registry+price join, geo distance,
  and price filtering.
- GitHub Actions CI (tests on Python 3.10/3.12, MCP import check, wheel build).

### Changed
- Filtering and sorting moved into a shared `core.query_stations` /
  `core.response_envelope` used by both the CLI and the MCP server.

## [0.0.1] - 2026-05-29

Initial release.

### Added
- `pitstop stations` — list and filter Italian fuel stations with their prices,
  by `--comune`, `--provincia`, `--brand`, `--near "lat,lon"` + `--radius`,
  `--fuel` (substring), `--self`/`--served`, with `--cheapest` and `--limit`.
- `pitstop fuels` — list the fuel-type names present in the dataset.
- `pitstop version` — print version metadata.
- JSON output (`--json`) with source/extraction-date provenance and a disclaimer.
- Local fetch + 24h cache of the MIMIT Osservaprezzi Carburanti station registry
  and daily price file, joined on `idImpianto` (stdlib only, no dependencies).
- Agent skill at `skills/pitstop/SKILL.md`.

### Known limitations
- Daily data, not real-time; Italy only.
- Some operators report placeholder prices (e.g. `1.000`); `--cheapest` can
  surface them. A sanity-floor is planned.
- `--fuel` is a substring match, so `Gasolio` also matches variants such as
  `Gasolio Alpino`.

[0.5.0]: https://github.com/galjos/pitstop/releases/tag/v0.5.0
[0.4.0]: https://github.com/galjos/pitstop/releases/tag/v0.4.0
[0.3.0]: https://github.com/galjos/pitstop/releases/tag/v0.3.0
[0.2.0]: https://github.com/galjos/pitstop/releases/tag/v0.2.0
[0.1.1]: https://github.com/galjos/pitstop/releases/tag/v0.1.1
[0.1.0]: https://github.com/galjos/pitstop/releases/tag/v0.1.0
[0.0.1]: https://github.com/galjos/pitstop/releases/tag/v0.0.1
