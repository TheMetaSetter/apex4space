# Research: responder hotspot MVP

Date: 2026-11-14. Branch: `anhkhoi-dev`; inspected HEAD: `819aa21`.
Scope: the local CSV → saved dataset → responder map path. No full science review.

## Observed state

- `app/storage.py:27–63` defines six existing tables. None of the three cell
  tables in spec §10.6 exists in code yet.
- `app/main.py:create_app` registers the point route and existing analysis,
  release, export, and health routes. It has no cell-map route.
- `scripts/prepare_data.py:parse_arguments` lacks `--input-csv`.
  `tests/test_sources.py:395–398` already expects that option. This is the
  previously recorded unfinished red test, not a passing baseline.
- `prepare_release` reads download progress; `check_release` also depends on it.
  Both need a real local-file path without fake download metadata.
- `SourceFileRecord.downloaded_at` currently requires a timestamp. Local CSV
  download time is unknown; it must not be replaced with file modification time.
- Current settings have an empty `science.grid` and select an empty 2026 release.
- `app/models.py` has 500 lines; `sources.py` has 499; `main.py` has 432;
  `storage.py` has 409. A focused cell module avoids overloading these files.
- Shapely is already declared. A projection library is not declared.
- The local VIIRS sample is 2023-07-12, not the configured 2026 window.
- Pytest collection found 30 cases. Collection is not a test run. The suite
  was not run while writing this plan.

## Input limits

Use existing local/Drive CSV evidence. All seven allowed FIRMS requests are
used. No new provider requests are authorized. Native pass/coverage data and
real named-area boundary files are not established by this inspection.

## Design boundary

The spec proposes six core tables, including stored area/day counts and cell
ID lists. Existing science tables remain unchanged outside the responder path.
This is a design, not current database behavior. See the new detail plan.

## Drive inspection update

On 2026-11-14, connected Drive folder listings confirmed eight CSVs in the
four sensor folders, plus excluded ZIP/notebook files at root. Only metadata
was read. The selected metadata responses did not expose provider checksums
or revision/version fields. No raw transfer or runtime OAuth preflight ran.
The [Drive plan](../plan/plan-drive-csv-preprocessing.md) records exact IDs/sizes
and separates connector access from the standalone preprocessing runtime.

## Three-table MVP update

The user now requires only `cell_detection`, `hotspot_cell`, and
`daily_hotspot_summary` in the new local database. Store raw observation fields
and assignment together in `cell_detection`. Source/release evidence stays in
manifest files. This supersedes the earlier six-table proposal, not the factual
research about the old database. Build a separate pilot; do not delete old data.

## Processed-only decision (not current runtime behavior)

The latest user request supersedes the three-table raw-retention design.
The new plan stores only hotspot_cell and daily_hotspot_summary, discarding
raw rows after in-memory assignment. No code or runtime verification changed
in this documentation turn. Earlier observations above describe the legacy code.
