# Databases by area

Use `data/areas/<area>/<release>/` for new processed databases.
Use simple folder names such as `south-america`, `viet-nam`, or `north-america`.
Each release folder contains `database.sqlite3`, `manifest.json`, and
`validation.json`. Choose a new release folder for each import.

Current files:

```text
mixed-areas/
  firms-v2/                 All nine original CSVs, including a global sample
  legacy-pilot/
    processed.sqlite3      Shared Africa sample and South America pilot database
    releases/              Original pilot manifests and validation records
```

The existing databases contain more than one area, so they stay together
under `mixed-areas`. Moving a folder does not filter its data.
Original CSV files stay in their input folder.

For example, run from the repository root with South America CSVs:

```sh
.venv/bin/python time-series-api/scripts/preprocess_firms.py --input "/path/to/south-america-csvs" --output-dir time-series-api/data/areas/south-america/release-1
```

Then check the result:

```sh
.venv/bin/python time-series-api/scripts/check_results.py --schema2-release-dir time-series-api/data/areas/south-america/release-1
```

The importer uses the supplied CSVs; the area folder name does not filter
coordinates. Supply only the files you want in that release.
The web app reads the release set by `storage.global_release_path` in
`config/settings.json`. It still uses one selected release at a time.
