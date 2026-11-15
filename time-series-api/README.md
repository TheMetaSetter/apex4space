# Time-series API

The current Frism website uses the checked North America Parquet release.
See [current data and rollback instructions](../web-app/README.md#current-parquet-release--15-november-2026).
The SQLite preparation and schema notes below remain available for the original releases.

_Processed emergency responder hotspot cell pilot · 14 November 2026_

---

## 📌 Current pilot

The verified processed release is `responder-local-pilot-2026-09-01-v1`. It covers 2026-09-01 UTC, the reviewed South America pilot rectangle, a 10 km EPSG:8857 grid, and the Aqua and Suomi-NPP platforms.

The release stores two active cells and one daily summary. Its status is `coverage_unknown`: these inputs do not include observation-opportunity data, so a count of zero would not establish that no fire was present.

This run used the downloaded local files selected in `config/processed-settings.json`. It made no Google Drive API or FIRMS network requests. The allowlist includes only the MODIS Terra/Aqua NRT 2026 CSV and VIIRS Suomi-NPP NRT 2026 CSV. Archive files and other sensors are outside this pilot.

## ⚙️ Prepare the local pilot

Run from `time-series-api/`. Set `FIRMS_INPUT_DIR` to the already downloaded local FIRMS folder. The settings file selects exact relative paths; the command does not ingest every file under that root.

```bash
python scripts/prepare_data.py \
  --settings config/processed-settings.json \
  --release-id responder-local-pilot-2026-09-01-v1 \
  --input-dir "$FIRMS_INPUT_DIR"
```

Validate the published database and release metadata:

```bash
python scripts/check_results.py \
  --settings config/processed-settings.json \
  --release-id responder-local-pilot-2026-09-01-v1 \
  --processed
```

The processed database is `data/areas/mixed-areas/legacy-pilot/processed.sqlite3`; release manifests and validation records are in `data/areas/mixed-areas/legacy-pilot/releases/`. The database has exactly two user tables: `hotspot_cell` and `daily_hotspot_summary`. The separate legacy database `data/service.sqlite3` is not modified.

Preparation writes temporary compact `.cells.json` checkpoints after each source passes its full-stream hash and unchanged-file checks. The checked release contains no CSV copy, raw row, row identifier list, FRP value, or raw-data table. The pilot checkpoints are removed after validation.

## 🗃️ Processed schema

| Table | Primary key | Stored fields |
| --- | --- | --- |
| `hotspot_cell` | `(grid_version, cell_id)` | Cell center in longitude/latitude and full GeoJSON polygon geometry. |
| `daily_hotspot_summary` | `(release_id, area_id, date)` | Nullable active-cell count, nullable sorted unique cell IDs, and day status. |

A release manifest binds the grid version and prepared area to source versions and hashes. Summary IDs resolve to cell shapes using that grid version; preprocessing checks the references. The ID list is not a SQL foreign key.

The state values distinguish known zero, missing input, partial input, available observations, and unknown coverage. The pilot’s one day is marked `coverage_unknown`.

## 📚 Input data dictionary

Each source row is one transient satellite hotspot detection record. The spatial reduction assigns its center to one equal-area grid cell. Records from the selected platforms and passes that land in the same cell on the same UTC day count once in the daily summary.

| Field | Meaning and units | Processing use |
| --- | --- | --- |
| `latitude`, `longitude` | Nominal fire-pixel center in degrees; coordinates identify a pixel center, not a confirmed ground fire point. [^1][^2] | Validated and projected into EPSG:8857; source coordinates are not stored. |
| `acq_date`, `acq_time` | Acquisition date and UTC time. [^1][^2] | Parsed to UTC and reduced to the declared UTC day. |
| `satellite` | Source satellite code; Aqua/Terra for MODIS and S-NPP/other platform codes for VIIRS. [^1][^2] | Validated against the allowlisted product and selected platforms. |
| `instrument` | Source instrument/platform label. | Checked against the selected product/platform mapping; not stored. |
| `version` | Collection plus processing mode such as NRT/URT. [^1][^2] | Every row is checked for a consistent collection base; compact version labels are retained in release metadata. |
| Brightness, scan/track, confidence, FRP, day/night, and type fields | Product-specific temperatures, pixel dimensions, confidence, fire radiative power, or labels. MODIS and VIIRS channels are not interchangeable. FRP is reported in MW by NASA. [^1][^2] | Headers are checked where applicable; these values are not used by the cell-count reducer and are not persisted. |

The observational hierarchy is detections → platform/pass and UTC time → cell/day memberships → one area/day summary. There are no subjects, replicates, treatment groups, or train/test split in this descriptive preprocessing. There is no coverage denominator. A missing day, partial source selection, zero count, and unknown coverage remain distinct; no values are imputed.

## 🌐 Query the processed map

The endpoint accepts exactly one prepared area or a containing EPSG:4326 bounding box, plus one UTC date:

```bash
curl -X POST http://127.0.0.1:8000/v1/hotspots/cells/query \
  -H 'Content-Type: application/json' \
  -d '{"release_id":"responder-local-pilot-2026-09-01-v1","date":"2026-09-01","area_id":"south-america-pilot-rectangle"}'
```

The response is a GeoJSON FeatureCollection with one polygon feature per selected cell, an `active_cell_count`, the selector, status, and warnings. GeoJSON positions use longitude/latitude (EPSG:4326). In OpenLayers, set `dataProjection: 'EPSG:4326'`, transform to the map view projection, and draw the cell layer above the basemap.

The processed route reads the two local tables and checked release metadata only. Legacy point, science, and export routes remain separate; processed releases return an explicit unsupported-dataset error for those raw/science paths.

## 📊 Pilot measurements

| Measure | Result |
| --- | ---: |
| Local source bytes scanned | 79,036,082 |
| CSV rows scanned | 929,011 |
| Rows used after date/platform/area selection | 3 |
| Cell/day memberships after deduplication | 2 |
| Unique hotspot cells | 2 |
| Saved processed database plus release metadata | 14,623 bytes |
| Python peak traced memory | 1,434,050 bytes |
| Peak resident memory | 75,759,616 bytes |
| Preparation elapsed time | 32.915 seconds |
| Published daily summaries | 1 |

The full command output is recorded in [the pilot report](../documents/logs/2026-11-14/detail/responder-hotspot-pilot-report.md). These are measurements for this narrow one-day pilot, not performance claims for archives or larger regions.

## 🧪 Verification

The earlier pilot check collected and passed 30 cases. The current suite has 40 passing cases, including schema-2 importer and area-query checks. The offline API checks call processed routes without reading CSV files or contacting Drive/FIRMS.

Run the suite from `time-series-api/`:

```bash
python -m pytest tests --collect-only -q
python -m pytest tests -q
```

## ⚠️ Scope and review

The schema-1 pilot above still represents two selected NRT files for one day and one rectangle. The separate schema-2 release below processes all nine downloaded files and all dates. Neither release establishes complete geographic coverage, fire perimeters, independent fire events, sensor equivalence, or FRP comparability.

The API and stored data have been checked offline. Visible Leaflet rendering with EPSG:6933 and the plain world background still needs visual review; this remains pending.

## 🔗 References

[^1]: NASA FIRMS. [MODIS Fire and Thermal Anomalies attribute descriptions](https://firms.modaps.eosdis.nasa.gov/content/descriptions/FIRMS_MODIS_Firehotspots.html).

[^2]: NASA FIRMS. [VIIRS Fire and Thermal Anomalies attribute descriptions](https://firms.modaps.eosdis.nasa.gov/content/descriptions/FIRMS_VIIRS_Firehotspots.html).

## All-date FIRMS release

Databases now live under `data/areas/<area>/<release>/`.
See [the area folder guide](data/areas/README.md) for the current layout and
commands for future imports. The original combined release stays under
`mixed-areas` because it includes a global sample.

The separate schema-2 database uses every valid row from the nine CSV files
inside the downloaded FIRMS folder. It covers 2000-11-01 through 2026-11-11.
The input files stay where they are; the importer reads them locally and does
not call Google Drive or FIRMS.

Use the standalone importer with any CSV file or folder. It finds CSVs in
subfolders, reads every date and sensor, and writes a new release directory:

```bash
python scripts/preprocess_firms.py \
  --input /path/to/firms-csv-folder \
  --output-dir data/areas/south-america/new-release
```

The output folder must not already exist. It contains `database.sqlite3`,
`manifest.json`, and `validation.json`. Check a release with:

```bash
python scripts/check_results.py --schema2-release-dir data/areas/south-america/new-release
```

The current checked release is `data/areas/mixed-areas/firms-v2`. Its ID is
`8796890e848f8a9ffb0ad255919fb7c469cdf6e0154fc50101139fd57dce6a49`. The
SQLite file has three processed tables: `hotspot_cell`, `hotspot_cell_day`,
and `daily_hotspot_summary`. It stores cell/day membership, not raw rows.

The area API currently accepts Viet Nam (`VN`, `VNM`, `Vietnam`, `Viet Nam`,
`Việt Nam`) and South America. A cell is included when its center is inside
the exact saved area polygon. GeoJSON uses longitude/latitude. Counts and
empty days carry `coverage_unknown`; a zero count does not mean no fire.
Requests return up to 10,000 cells per page and daily summaries for up to 366
days. Leaflet must set its map projection separately; ordinary GeoJSON stays
EPSG:4326 even when the map uses EPSG:6933.

```json
{"release_id":"8796890e848f8a9ffb0ad255919fb7c469cdf6e0154fc50101139fd57dce6a49","area_name":"South America","date":"2026-11-11","page_size":1000}
```

Send this to `POST /v2/hotspots/query`. The full active count is `1083`; the
first page returns 1000 cells and the next returns 83 with the same count.
Use `POST /v2/hotspots/summaries/query` for daily counts, with an exclusive
`end_date`.
