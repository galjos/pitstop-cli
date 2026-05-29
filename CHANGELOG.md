# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.0]: https://github.com/galjos/pitstop/releases/tag/v0.1.0
[0.0.1]: https://github.com/galjos/pitstop/releases/tag/v0.0.1
