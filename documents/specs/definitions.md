# Time-series API terms

Status: shared glossary for spec and web discussions. It records the current
team choices. The schema draft is in the development spec, §10.6. Neither
document changes the implemented API or database contract by itself.

## Map and data terms

- **Area of interest (AOI):** The area selected for a map query. The MVP uses
  a rectangle in the current API. The draft adds stored named areas through
  `area_id`; drawn polygons remain later work.
- **Grid:** The fixed set of cells used to assign detections. The team defines
  `w` as each cell's side width in kilometres. The projection, origin, cell ID
  rule, and edge rule must be saved with each grid version.
- **Grid cell (cell):** One unit of the grid. A cell ID is meaningful only
  with its grid version.
- **Source detection (detection):** One point record from a satellite fire
  product. It has a location, time, platform, and source values. It is not a
  confirmed wildfire or a count of separate fire incidents.
- **Cell assignment:** A temporary preprocessing step that maps a detection
  center to one grid cell. The processed-only MVP stores no detection link.
- **Hotspot (hotspot cell):** A grid cell with one or more selected detections on a UTC
  day. For one day and area, the API returns these cells as the map hotspots.
  If both MODIS and VIIRS detect a cell, it remains one cell; keep the sensor
  values separate.
- **Observed hotspot count:** The number of selected source detections. It is
  not the number of hotspot cells or separate wildfires.
- **Daily hotspot count (`active_cell_count`):** The number of distinct detected
  cells for one UTC day, area, release, and selected platforms. A cell seen by
  several platforms counts once. It is not the number of source detections.
- **Daily hotspot summary:** Proposed stored area/day count in
  `daily_hotspot_summary`, keyed by release, area ID, and UTC date. It holds
  nullable `active_cell_count`, nullable sorted unique `hotspot_cell_ids`,
  and `status`. The release fixes the source
  selection and boundary version. This replaces the earlier derived-only design.
- **Cell geometry:** The shape of one full grid cell. It may appear as a
  rectangle or a polygon on the map after a projection or boundary clip.
- **Clipped display geometry:** The part of a full cell drawn inside the
  selected area. Clipping changes the displayed shape only. It does not change
  the cell ID or full-cell metrics. The result may be a GeoJSON `Polygon` or
  `MultiPolygon`.
- **Area cell rule:** Include a cell when its center is inside the requested
  area. Keep the full-cell metrics, then clip the shape for display. This
  matches the current spec.

## Fire radiative power and coverage

- **Raw FRP:** A source sensor's fire radiative power value, in megawatts
  (MW). Keep the value unchanged. MODIS and VIIRS raw FRP are not directly
  comparable.
- **Per-pass cell FRP sum:** The sum of valid raw FRP values for one cell,
  platform, and satellite pass. It is available only when pass and quality
  data support the sum.
- **Daily peak cell FRP:** The highest valid per-pass cell FRP sum for one
  cell and one platform during a UTC day. It is an observed power value, not
  energy. Do not combine platforms before an independent comparison passes.
- **Coverage:** Evidence that a sensor made a usable observation over an area
  or cell. No detection means zero only when usable coverage confirms a visit
  with no detection. Without that evidence, the result is unknown.
- **Pass:** One satellite visit over an area.

## Data and API terms

- **Release:** A fixed set of source data, settings, and checked results.
  A change creates a new release.
- **Grid version:** The saved grid width, projection, origin, ID rule, and
  edge rule. A different grid creates a different version.
- **Source-only release:** A release that serves original detections but has
  no validated daily FRP or harmonized count method. Unknown coverage stays
  unknown.
- **Cell map feature:** Proposed GeoJSON output for one hotspot cell, day, and
  area. Sensor values stay separate. The user chose a separate cell route so
  the current point route stays unchanged. The proposed path is
  `POST /v1/hotspots/cells/query`; its fields and web review are still open.

## Wording rules

- Use **source detection** for one raw point record.
- Use **hotspot cell** for one detected grid cell on one UTC day.
- Avoid **fire event** when it could mean a separate real-world wildfire.
- Use **daily hotspot count** for cells and keep its metric name
  `active_cell_count`. The legacy API name `observed_hotspot_count` still
  counts source detections; do not change its meaning.
- Do not call a missing value zero. Name the reason, such as unknown coverage.

## Open API contract details

- The user chose center-based area selection. This matches the current spec.
- The user chose to keep `/v1/hotspots/query` for points and add a separate
  cell route. The proposed path and response fields need review before the
  API contract changes.

## Processed-only MVP

Only `hotspot_cell` and `daily_hotspot_summary` are stored as local dataset
tables. Source detections and FRP stay in Drive and are used transiently during
preprocessing. Release manifests retain source hashes and filter rules, not
raw rows. The older local raw-retention decision is superseded.
