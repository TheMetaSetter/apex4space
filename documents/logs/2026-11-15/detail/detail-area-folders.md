# Area database folders

- [x] Inspect database manifests and current settings.
- [x] Compare moving folders, splitting databases, and rebuilding each area.
- [x] Choose moving folders: simplest, with no reprocessing.
- [x] Move the nine-file release to `data/areas/mixed-areas/firms-v2`.
- [x] Move the shared pilot database and metadata to `data/areas/mixed-areas/legacy-pilot`.
- [x] Verify all eight moved files keep the same inode, size, and modification time.
- [x] Update both settings files, current guides, and the development spec.
- [x] Document `data/areas/<area>/<release>` for future imports.
- [x] Check both settings files resolve and the pilot SQLite quick check passes.
- [x] Load web config and query the moved database: 34 Viet Nam cells on 2023-07-12.

The combined release includes a global sample. The old pilot database
contains the Africa sample and South America pilot. Neither is relabeled
as a single area. Historical logs retain the paths used at that time.
Raw input files stay in place. Database contents and release IDs are unchanged.
No source code or importer behavior changed.
The web server remains stopped. The full pytest suite was not run because
pytest is not installed in the current environment; the former temporary
test environment no longer exists.
