# FIRMS web data contract (FE/BE handoff)

## Product semantics

The primary map unit is `cell_day`: one 1 km equal-area grid cell on one UTC
date. It summarizes detections, not a unique fire, wildfire perimeter, or
incident. A single incident can span many cells and dates; separate nearby
incidents can fall in the same cell-day. Label charts as hotspot activity or
cell-days, never as fire counts/incidents.

## Data products in this folder

- `calendar_monthly_by_sensor.json`: sensor-native monthly observation metrics.
- `event_calendar_monthly.json`: monthly observation, cell-day, sensor-mix,
  Terra-baseline, and fire-type metrics. The legacy `event_` filename is kept
  for compatibility; its rows are cell-day activity, not fire events.
- `hotspots_2023-07-12.geojson`: raw-detection map sample for one date.
- `hotspot_cell_days_2023-07-12.geojson`: aggregated cell-day map sample for
  one date.
- `data_manifest.json`, `event_harmonization_manifest.json`: lineage and
  build metadata.

## Metrics and safe aggregation

- `observations`: source rows (sensor detections); repeat observations are
  expected.
- `hotspot_cell_days`: unique grid-cell/date units in the dataset for that
  month, across available sensors.
- `terra_backbone_cell_days`: cell-days with Terra MODIS observations. This is
  the recommended consistent sensor-specific baseline for long-term comparison.
- `terra_only_cell_days`: cell-days observed by Terra and no other sensor.
- `multi_sensor_cell_days`: cell-days where more than one sensor contributed.
- `detections_by_satellite` and `cell_days_by_satellite`: keep sensor series
  separate. Do not add sensor-specific cell-days to get the union; use
  `hotspot_cell_days`.
- `frp_max_by_satellite`: retain and label by satellite. Do not average, sum,
  rank, or present this as calibrated cross-sensor FRP.
- fire-type monthly categories are mutually exclusive and sum to
  `hotspot_cell_days`: vegetation type 0 only, other known types 1-3 only,
  unknown only, and mixed/partly unknown. Type 0 means presumed vegetation
  fire. Unknown is not vegetation.

The Terra baseline reduces changes caused by adding VIIRS to the observing
network, but remains a Terra-only hotspot activity series, not a sensor-neutral
estimate of fire incidence or burned area. Do not infer that MODIS and VIIRS
confidence or FRP values are directly comparable. No cross-sensor calibration
was applied because no reference fire/perimeter validation set or validated
overlap model is part of these inputs.

## Dynamic map/API expectation

The GeoJSON files here are examples, not a complete time-series map API. The
backend should query the retained `processed/quality_controlled/` source tables
(or load them to a spatial/columnar store), filter by UTC date range and AOI,
then return only matching rows/cell-days. Apply the same equal-area cell index
and 1 km resolution described in `event_harmonization_manifest.json` to
reproduce cell-day IDs. Return paginated or viewport-bounded results; never
transfer all 84.9 million rows to the browser. Keep raw detections available
when users need sensor/source detail.

Suggested endpoint shape (backend implementation is owned by BE):

```text
GET /api/hotspots?date=YYYY-MM-DD&bbox=west,south,east,north&sensor=VIIRS_SNPP
GET /api/hotspot-cell-days?start=YYYY-MM-DD&end=YYYY-MM-DD&bbox=...
GET /api/calendar?start=YYYY-MM&end=YYYY-MM&metric=terra_backbone_cell_days
```

Treat NRT as provisional, preserve `product_type`, `version`, source lineage,
UTC timestamps, and missing `fire_type`; do not impute absent type or confidence.
