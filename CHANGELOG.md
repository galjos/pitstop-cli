# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.2] - 2026-06-26

Documentation/package-description patch. The README status section still
described the v0.9.0 milestone even though the current public release line is
1.0.x. This release updates the packaged README to match v1.0.2, corrects a CLI
example that used an MCP tool name, and lists the full MCP tool surface.

## [1.0.1] - 2026-06-10

Metadata-only patch. The 1.0.0 wheel on PyPI was built and uploaded before the
GitHub repo was renamed `pitstop` → `pitstop-cli`, so its `Project-URL`
entries (Homepage / Repository / Changelog / Issues) point at the pre-rename
URLs. PyPI wheels are immutable, so this release supersedes 1.0.0 with
corrected metadata. No code changes.

## [1.0.0] - 2026-06-02

First public release. Nine months of iteration condensed:

- **Italian fuel prices** — MIMIT Osservaprezzi Carburanti, ~23.8k stations,
  joined daily, four layers of data-quality defense (`--min-price` floor,
  `--fresh-within-days` freshness, combined 15% + Tukey IQR outlier rule,
  ISTAT-derived comune-coordinate validation). Cross-validated against
  MIMIT's own published regional averages and spritpreise.it (South Tyrol)
  — matches to within ~½ cent across all 21 regions.
- **EV charging** — OpenStreetMap via Overpass, with operator tariff-page
  URLs attached per result (per-station €/kWh prices aren't in open data
  yet; see v0.8.0 notes).
- **CLI + MCP server** — same core, two surfaces. Five MCP tools:
  `list_fuels`, `find_stations`, `find_cheapest`, `find_chargers`,
  `get_stats`.
- **Agent ergonomics** — multi-fuel queries, international comune names
  (EN/FR/DE: Rome, Bozen, Mailand, Venise, …), navigation URLs,
  GeoJSON output, structured Overpass errors.
- **MIT licensed**, Python ≥3.10, stdlib-only runtime (MCP server needs
  the optional `[mcp]` extra). 38 tests, GitHub Actions CI.

### Added in 1.0.0 (vs 0.9.0)
- LICENSE (MIT).
- PyPI-ready packaging: classifiers, project URLs, license metadata.
- OpenClaw frontmatter on the agent skill (`metadata.openclaw.requires`
  + `install` hints for `uvx` and `pipx`) so the skill is publishable
  to ClawHub-style registries.
- README intro rewritten for non-Italian audiences.

## [0.9.0] - 2026-06-02

### Added
- **Multi-fuel query support.** The `--fuel` flag now accepts a comma-separated
  list of fuels (e.g. `--fuel "Benzina,Gasolio"`). This allows retrieving and
  ranking multiple fuel types in a single request, which is much more efficient
  for agentic interactions.
- **International Municipality Mapping.** Added a `BILINGUAL_MAP` in
  `geocoding.py` that resolves common English, French, and German names for
  major Italian cities (e.g. Rome/Rom/Naples/Mailand/Venise) to their Italian
  equivalents in the dataset.
- **Improved Coordinate Resilience.** `query_stations` now prioritizes the
  **calculated centroid** of all stations in a municipality (robust for 
  $N \ge 3$) over the external ISTAT reference coordinate. This makes the 
  `coordinate_suspect` flagging much more resilient to errors in the external 
  comune-coordinate file (e.g. the Bolzano center bug).
- **JSON Error Reporting for Overpass.** Fetch errors from the Overpass API 
  (EV chargers) are now captured and surfaced inside the JSON response envelope
  under an `error` field. This allows callers to distinguish between "no 
  chargers found" and "service currently unavailable".

### Changed
- `chargers.find_chargers` and `overpass.fetch_elements` now return a tuple
  `(data, error)` to facilitate structured error reporting.

## [0.8.0] - 2026-06-01

### Added
- **EV operator tariff URLs.** Each charger result now carries a
  `tariff_info_url` pointing to the operator's official tariff page (when the
  operator is recognized). The CLI prints a footnote like
  `5/5 stations have an operator tariff page`. New `cpo_tariffs.py` module
  with a substring-matching registry covering the major Italian CPOs:
  Alperia, Neogy, Enel X Way, Be Charge, Free To X, Ionity, Tesla,
  Plenitude, Atlante, Repower, A2A, Edison, Acea, EVway, and others.
- MCP `find_chargers` tool description now instructs the agent to surface
  `tariff_info_url` when the user asks about price instead of guessing.

### Why this isn't real per-kWh prices
The honest finding from a thorough investigation:
- **AFIR DATEX II** (since 14 Apr 2026) is a CPO→NAP *upload* channel — there
  is no documented public consumer-query endpoint.
- **Italy's PUN** (piattaformaunicanazionale.it) is an ArcGIS-backed SPA with
  no documented public REST API for tariffs.
- **Chargeprice** and **Eco-Movement** carry per-station tariffs but require
  paid licenses.
- **OSM** has only `fee=yes/no` (already surfaced), not actual €/kWh.

So per-station tariffs are not openly machine-readable in Italy in mid-2026.
Surfacing the operator's own tariff page is the most useful + honest thing
the tool can do today. Revisit when AFIR data consumer-side matures.

## [0.7.0] - 2026-06-01

### Added
- **EV charging stations.** First step into the EV domain: a new `pitstop
  chargers` CLI command and an MCP `find_chargers` tool backed by
  OpenStreetMap via the **Overpass API** (open, no key required, ODbL-licensed
  with attribution in output).
- Filter by `--operator`, `--socket` (plug-type substring), `--min-power` kW,
  `--fast` (≥50 kW), `--ultra-fast` (≥150 kW), `--free`, `--public`. Center
  the search on a comune (`--comune NAME`, resolved via the existing
  comune-coords reference) or a coordinate (`--near "lat,lon"`).
- Per-charger output includes operator, plug types and counts, max kW, fee,
  access, and distance.
- 7-day on-disk cache for Overpass results (charger metadata changes slowly).

### Why
EV charging was the genuinely-different next data domain on the roadmap.
Italy/EU don't have a single open per-station price feed yet (AFIR
NAP/DATEX II is maturing but uneven), so v0.7.0 focuses on **locations and
capabilities** — operator, plug types, max kW, fee, access — which is what
"where can I charge near X" needs. Pricing is the planned next layer.

### Notes
- Open Charge Map's API now requires a registered key (HTTP 403 without);
  OSM Overpass is fully open and well-covered for EU chargers, so it's the
  pragmatic choice for v0.7.0.

## [0.6.0] - 2026-05-30

### Added
- **Tukey IQR outlier rule** combined with the existing 15% deviation rule —
  catches borderline misreports in tight markets that the percentage rule
  alone misses. A price is now flagged `outlier` if it is more than 15% below
  the (fuel, provincia) median **or** below the Tukey lower fence
  (Q1 − 1.5·IQR).
- `--drop-outliers` CLI flag and `drop_outliers` MCP parameter that filters
  any price flagged outlier. MCP `find_cheapest` defaults `drop_outliers=True`
  for clean cheapest answers.

### Why
A user cross-checked v0.5.0's €1.787 "cheapest BZ Gasolio" (g.p. oil) against
[spritpreise.it](https://www.spritpreise.it/), a local South-Tyrol fuel
service. That station/price does not appear there and spritpreise's cheapest
is €1.989. Empirically only 1 of 250 BZ Gasolio prices in MIMIT falls below
€1.989 — the g.p. oil misreport. Its deviation is −14.9%, just under the 15%
percent rule. The Tukey fence (€1.949 for BZ Gasolio, IQR €0.080) catches it.

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

[1.0.2]: https://github.com/galjos/pitstop-cli/releases/tag/v1.0.2
[1.0.1]: https://github.com/galjos/pitstop-cli/releases/tag/v1.0.1
[1.0.0]: https://github.com/galjos/pitstop-cli/releases/tag/v1.0.0
[0.9.0]: https://github.com/galjos/pitstop-cli/releases/tag/v0.9.0
[0.8.0]: https://github.com/galjos/pitstop-cli/releases/tag/v0.8.0
[0.7.0]: https://github.com/galjos/pitstop-cli/releases/tag/v0.7.0
[0.6.0]: https://github.com/galjos/pitstop-cli/releases/tag/v0.6.0
[0.5.0]: https://github.com/galjos/pitstop-cli/releases/tag/v0.5.0
[0.4.0]: https://github.com/galjos/pitstop-cli/releases/tag/v0.4.0
[0.3.0]: https://github.com/galjos/pitstop-cli/releases/tag/v0.3.0
[0.2.0]: https://github.com/galjos/pitstop-cli/releases/tag/v0.2.0
[0.1.1]: https://github.com/galjos/pitstop-cli/releases/tag/v0.1.1
[0.1.0]: https://github.com/galjos/pitstop-cli/releases/tag/v0.1.0
[0.0.1]: https://github.com/galjos/pitstop-cli/releases/tag/v0.0.1
