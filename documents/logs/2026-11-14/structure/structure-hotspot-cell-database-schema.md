# Processed hotspot schema

Date: 2026-11-14. Status: current MVP design; no database migration applied.

The latest user request supersedes earlier local raw-retention decisions.

| Local table | Purpose |
| --- | --- |
| `hotspot_cell` | One full shape and center per detected grid cell/version. |
| `daily_hotspot_summary` | One area's daily unique cell IDs, count, and status. |

Do not create `cell_detection` or keep raw rows in the new dataset. Stream
Drive CSVs, build unique day/cell sets, verify each source, and discard raw input.
Keep small source/release/grid/filter metadata files and the versioned catalog.
The count equals the length of the unique cell-ID list; unknown is not zero.

Website → API → daily_hotspot_summary → hotspot_cell shapes → GeoJSON
features + daily hotspot count → OpenLayers map and count display.

The [spec §10.6](../../../specs/time-series-api-devspec.md#106-hotspot-cell-schema-draft--2026-11-14)
owns the exact fields. The [new checklist](../detail/detail-responder-hotspot-mvp.md)
owns planned file changes/signatures. Original user databases are untouched.
