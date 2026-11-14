# FIRMS MODIS–VIIRS data pipeline

This document describes how the four FIRMS platform files become the web data
package in `data/`. The scripts in `tools/` are the executable pipeline. The
four source CSVs and the large quality-controlled tables are not stored in this
application repository; keep them in approved local or object storage and
provide them to the processing environment.

## Processing sequence

Run from the data workspace root after placing the four FIRMS inputs under
`Data/` and configuring the South America boundary file:

1. `build_data_catalog.py` inventories inputs, sizes, schemas, and date ranges.
2. `validate_sensor_schemas.py` checks the MODIS and VIIRS source headers and
   maps them to the expected source fields.
3. `filter_to_boundary.py` applies the selected polygon boundary and records
   source filename and row number for lineage.
4. `normalize_sensor_data.py` standardizes field names, numeric types, UTC
   acquisition timestamps, platform/sensor labels, product/version metadata,
   original confidence, and fire-type values. Original confidence is retained;
   the convenience confidence score is explicitly heuristic.
5. `merge_by_sensor.py` consolidates each platform's archive/NRT inputs while
   retaining sensor/platform and product provenance.
6. `apply_quality_controls.py` applies row-level checks and writes one retained
   canonical table per platform under `processed/quality_controlled/`.
7. `validate_processed_pipeline.py` audits retained-table schema, coordinate
   ranges, timestamps, FRP, confidence, and source lineage.
8. `build_web_data.py` streams the four canonical tables to generate
   `calendar_monthly_by_sensor.json`, a point GeoJSON example for one UTC day,
   and `data_manifest.json`.
9. `harmonize_hotspot_clusters.py` projects detections to a common 1 km
   equal-area grid, aggregates by grid cell and UTC day, and generates
   `event_calendar_monthly.json`, a one-day cell-day GeoJSON example, and an
   event-harmonization manifest.
10. `validate_web_data.py` checks the generated web package and records the
    result in `reports/web_data_validation.json`.

The exact commands and options are documented in the script help and root
workspace README. The output package and field contract are documented in
`data/README.md` and `data/API_DATA_CONTRACT.md`.

## Final web outputs

- `data/event_calendar_monthly.json`: recommended harmonized activity calendar.
  The unit is an active 1 km equal-area cell on one UTC day (cell-day), not a
  unique fire or incident.
- `data/calendar_monthly_by_sensor.json`: monthly detections and FRP summaries
  grouped by sensor, platform, product type, version, and fire type. This is
  sensor-stratified; do not add sensor FRP values as if they were calibrated.
- `data/hotspot_cell_days_YYYY-MM-DD.geojson`: one-day cell-day map example.
- `data/hotspots_YYYY-MM-DD.geojson`: one-day point observation map example.
- `data/data_manifest.json` and
  `data/event_harmonization_manifest.json`: scope, counts, exclusions, and
  aggregation metadata.

The GeoJSON files in the handoff are samples for the selected date, not a
complete map archive or a dynamic endpoint. A backend should load/index the
canonical observation tables in a database or object store and query by date
and AOI. Do not send the full archive to a browser.

## Interpretation and known limits

- A cell-day removes repeated same-cell/day observations from the activity
  count while preserving sensor-specific counts and FRP summaries. It does not
  link detections into unique fire incidents.
- MODIS and VIIRS confidence and FRP remain on their source scales. No
  cross-sensor confidence probability or FRP correction is claimed.
- Missing FIRMS `fire_type` remains unknown. Type 0 means presumed vegetation
  fire; known non-vegetation codes remain separate.
- All-sensor cell-day totals may shift as sensor availability changes. For a
  long-running sensor-specific trend, use the Terra backbone field described
  in `data/README.md`.
- Archive and NRT observations are distinguished by product metadata; recent
  NRT data are provisional.

