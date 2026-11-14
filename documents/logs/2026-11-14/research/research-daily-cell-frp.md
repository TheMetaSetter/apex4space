# Daily FRP and shared cells

Date: 2026-11-14

- This note checks the spec, runtime, OpenAPI, and primary sources. After the
  user clarified `w` and the daily value, the spec and checklist were updated.

## Matches

- The spec proposes a 1 km equal-area grid and says to record its size and
  version. It also says a grid alone does not make the sensors comparable.
- `DailyRecord` already has a cell ID, cell shape, cell center, day, source
  count, optional reference count, coverage, and status.
- The runtime assigns whole grid cells to a requested rectangle by testing
  each cell center. It separately selects raw observation points by their
  coordinates. This is not yet the proposed record-to-cell assignment.
- The raw observation record and point response keep each source FRP value in
  MW. No correction is applied to that raw value.
- `active_cell_count` exists as an optional metric. It counts cells with
  detections and is separate from detection count.
- The spec already requires matched MODIS–VIIRS passes, footprint checks,
  unmatched records, and tests of the FRP observation operator.

## Conflicts and missing decisions

- The spec's grid is a 1 km proposal. It does not define a global tunable
  `w × w` grid. A global grid needs a width unit, equal-area projection,
  origin, cell IDs, and a fixed edge rule. Degree squares do not have a fixed
  ground area around the world.
- The proposed cell rule says a record belongs to the cell that contains the
  record's center. The current runtime does not assign point records to cells.
- A cell's hotspot flag needs a time and source rule. No detection can mean
  either no detected hotspot or no usable observation. Coverage must keep
  these states separate.
- The spec defines `frp_pass_sum_mw` for one satellite pass. It says not to
  sum values across different times and call the result emitted energy. The
  API rejects day/month aggregation for this metric.
- There is no daily FRP metric. `DailyRecord` and `analysis_daily` store no
  FRP value. OpenAPI lists `frp_pass_sum_mw`, but does not offer a daily FRP
  result.
- The spec plans an FRP operator test. It does not compare a plain global
  ratio or linear adjustment as a separate simplest candidate.
- “Daily FRP” is not defined. A sum across all detections and passes may count
  repeat observations. FRP is power in MW at an observation time, not energy
  over a day.

## Small experiment path

- Keep each original per-record FRP value unchanged.
- Assign each observation center to one fixed equal-area cell. Keep the cell
  size `w` and grid version with the release.
- For each cell and pass, sum valid FRP separately for MODIS and VIIRS. Compare
  paired, near-time passes on matching ground areas. Keep missing coverage
  separate from a valid zero.
- First measure the uncorrected difference. Then test one simple scale or
  linear correction on tuning data. Keep it only if it improves held-out
  dates or areas. Report errors by FRP range, day/night, scan angle, and area.
- Do not use one global factor as an assumed truth. A published comparison
  found that sensor differences change with spatial scale, ecosystem, fire
  size, and viewing angle.
- If the team needs one daily number, a possible simple definition is the
  highest valid area-wide pass sum during the UTC day. Call it a daily peak
  observed pass FRP, in MW. Do not sum different passes and call it daily
  emitted energy. This rule still needs team approval and validation.
- Keep a combined or corrected daily value unavailable until an independent
  test passes. A map can still show raw sensor-specific points and values.

## Team choices and current gap

- The user chose `w` as cell side width in km, not the number of grid rows or
  columns. T9 still needs to freeze the equal-area projection, origin, cell ID,
  edge rule, and a tested value of `w`.
- A cell is active for a UTC day if either sensor has a selected detection in
  it. Keep counts and presence by platform separate.
- The user chose the highest valid pass sum in one UTC day as the daily value.
  Since MODIS and VIIRS are not yet comparable, the spec defines one peak per
  cell and platform. It does not add different passes or combine platforms.
- Report zero only when usable coverage confirms a visit with no detection.
  Unknown coverage stays unknown. A hotspot alone does not show that a cell
  had a usable visit when it had no detections.
- The simple comparison order is: (1) compare uncorrected cell/pass sums on
  paired, near-time passes with matching usable area; (2) fit one scale factor
  on tuning data; (3) keep it only if it improves results on held-out dates and
  areas. This is an experiment, not an approved universal correction.
- This plan fits the spec's warning that a grid alone does not make sensor
  values comparable. The current API still exposes raw point FRP and a
  pass-only area sum. It has no daily cell FRP result.
- The web developer approved rectangle queries and point paging. A cell map
  needs a separate review of its geometry, values, and coverage states before
  the OpenAPI contract changes.

## Sources

- Development spec v0.4: §§3.1, 7.2–7.4, 9 Step B, and 10.2.
- Runtime: `app/models.py`, `app/analysis.py`, `app/main.py`, and
  `openapi.json` in `time-series-api/`.
- [NASA VIIRS product guide](https://viirsland.gsfc.nasa.gov/Products/NASA/FireESDR.html):
  VIIRS product resolutions and the continuity role of the 750 m product.
- [NASA VIIRS 375 m active-fire algorithm guide](https://viirsland.gsfc.nasa.gov/PDF/VIIRS_activefire_375m_ATBD.pdf):
  FRP uses pixel area, radiance difference, and a sensor coefficient; pixel
  area varies with scan angle; I4 saturation affects retrieval.
- [Li et al. 2018, MODIS–VIIRS FRP comparison](https://doi.org/10.1029/2017JD027823):
  paired-sensor FRP differences vary with scale, ecosystem, fire size, and
  view angle. The reported 1-degree-grid difference is not a universal
  correction factor for smaller cells.
