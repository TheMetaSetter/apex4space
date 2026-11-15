# Load the Parquet release into Frism

## Pass 1 — Check and describe
- [x] Record file hashes, dates, schema, country codes and grid rules.
- [x] Check every month for duplicate keys and valid grid coordinates.
- [x] Match source country codes to North America membership.
- [x] Rebuild cell corners from the supplied formula.
- [x] Document country attribution, discarded detections, partial years and coverage.

## Pass 2 — Connect the backend
- [x] Read source Parquet directly with DuckDB; preserve input files.
- [x] Add release selection while retaining SQLite rollback.
- [x] Share queries across daily maps, summaries, years, calendar and chat.
- [x] Deduplicate continent cell/day membership across countries.
- [x] Preserve paging and return source/grid provenance.
- [x] Transform source cells for display without regridding.

## Pass 3 — Load and verify
- [x] Verify the 2024 reference, border cells, leap days and partial years.
- [x] Check speed, paging, geometry and chat data context.
- [x] Switch the checked release into all views; update labels.
- [x] Check colors, logo, panels and no-scroll behavior.
- [x] Document use and rollback.

## Results

- Release: 50589b4e46f939cc682ffb4e6bf940fad69e95e25a1a908a1074ab675adad721.
- Metadata: time-series-api/data/areas/north-america/parquet-v1/.
- All 313 files and 150,615,549 rows checked. No null required fields, duplicate
  country/cell/day keys, bad date partitions or invalid/out-of-bounds grid IDs.
- Continuous monthly sequence; all source SHA-256 hashes rechecked after integration.
- North America: 9,812,070 country/cell/day rows before border deduplication.
  Forty member-country codes have rows. BJN and SER have none.
- 2024: 91,057 distinct cells, 749,373 cell-days, peak 2024-05-02 (5,046 cells).
- 2025: 92,094 distinct cells, 706,933 cell-days.
- Existing daily summary and new annual query agree on 749,373 for 2024.
- Full 2024 paging: 91,057 unique cells across pages in 2.58 seconds locally.
- 50 tests passed; JavaScript syntax check passed.
- Source corner formula checked against pyproj, including negative indices.
  Nominal edge cells are clipped to Mercator display bounds; IDs are retained.
- Explore, Compare and Discover visually checked against the new counts.
- Phone 390x844 and desktop 727x852 checked; body matches viewport size.
  Phone filter contents fit their panel; only comparison stats scroll.
- Calendar leap day opens Explore on 2024-02-29 with 1,730 cells.
  Mobile comparison tabs and summary close/reopen were exercised.
- SQLite rollback settings tested: the original equal-area release still returns
  1,669 cells on the same day. No cross-grid data is merged.
- Chat tests verify Parquet stats and source projection reach the local model
  interface. Live Gemma remains unverified because Ollama is not running;
  this existing runtime dependency is unchanged by the data migration.

## Files and semantics

No raw CSV, source Parquet or old SQLite database was modified. The validator
publishes metadata only. Daily/year/summary/chat request paths stay unchanged;
new response metadata describes EPSG:3857 and the producer's country rule.
The supplied producer script was read and hashed, not executed. Its deletion
and output commands were not treated as user instructions.

Default validator arguments are all explicit: input, output, catalog and producer
script are required. Runtime defaults are SQLite for older settings, a six-year/
area aggregate cache, two DuckDB scans, 512 MiB per scan, and a 30-second timeout.
Current settings explicitly select Parquet and the checked release. Setup and
rollback are documented in web-app/README.md. Future Parquet revalidation can
use scripts/prepare_parquet.py with a new output folder.

Follow-up: the later global-range work verified live Gemma successfully with
two real overlapping ranges; see detail-global-ranges.md and global-live-chat-check.json.
