---
date: 2026-11-14
status: approved-for-execution
related_research: ../research/research-firms-all-dates.md
---
# Structure: all-date FIRMS database and named-area backend

## 📋 Proposed delivery order

| Phase | Outcome | Dependency | Complete when |
| --- | --- | --- | --- |
| 1 | Frozen input, grid, schema, and area contracts | Resolve polar policy; use approved compact third table | Selected contracts and terminology map are reviewed. |
| 2 | Portable Python script builds a complete small database | Phase 1 | Arbitrary filenames, overlapping files, and multiple dates pass one end-to-end fixture. |
| 3 | Country/continent names resolve to local polygons | Phase 1 | USA, Viet Nam, North America, ambiguity, and unknown-name cases resolve correctly. |
| 4 | Backend returns paged shapes and full daily counts | Phases 2–3 | Polygon queries and summaries agree across pages without source reads. |
| 5 | Every supplied CSV/date is processed and independently checked | Phases 2–4 | Full inventory reconciles, all dates are represented, hashes pass, and resource measurements are recorded. |
| 6 | Leaflet handoff, documentation, and rollout | Phase 5 | Custom CRS contract is documented; visual approval is recorded separately. |

The user explicitly directed execution of the linked plan from top to bottom. That instruction approves this phase order for execution. The all-row polar policy assigns EPSG:6933 to −86°..+86° (inclusive), EPSG:6931 to latitudes above +86°, and EPSG:6932 below −86°. The user previously approved the compact third processed table. The formal detail checklist records these decisions and is the execution guide.

The pilot database remains separate and unchanged by the global release. Frontend implementation and visual review remain outside the current backend/importer execution.
