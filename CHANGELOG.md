# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.0.1]: https://github.com/galjos/pitstop/releases/tag/v0.0.1
