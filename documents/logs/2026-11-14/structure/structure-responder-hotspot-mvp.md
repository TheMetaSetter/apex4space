# Processed hotspot MVP: structure

Date: 2026-11-14. Status: proposed; implementation paused.

The latest user instruction replaces raw retention and the three-table design.
Only `hotspot_cell` and `daily_hotspot_summary` are stored as dataset tables.
Drive rows are transient; metadata files retain source identity/hashes and filters.

| Phase | Stages | Result |
| --- | --- | --- |
| 1 | Baseline; contracts; Drive access | Checked records/settings and usable runtime access. |
| 2 | Grid; stream reducer; summaries | Verified processed cell sets without local raw files. |
| 3 | Publication; reads | Exactly two tables plus checked compact metadata. |
| 4 | GeoJSON response; route | Local-only map and daily count, with clear statuses. |
| 5 | Pilot; handoff | Offline reads verified and web feedback recorded. |

Follow each stage in order with failing checks first and at most 30 collected
cases. See the [detailed checklist](../detail/detail-responder-hotspot-mvp.md)
and [Drive input plan](../plan/plan-drive-csv-preprocessing.md). No execution
or deletion of existing user files is authorized by this planning document.
