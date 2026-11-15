# Reuse the FIRMS tools

## Database folders

```text
time-series-api/data/areas/
├── mixed-areas/
│   ├── firms-v2/
│   └── legacy-pilot/
├── south-america/
├── viet-nam/
├── north-america/
└── russia-asia/             Created by the next import
```

Store each new database in `<area>/<release>/`. A new release contains
`database.sqlite3`, `manifest.json`, and `validation.json`.
The existing mixed databases stay together because they contain several areas.

## Import Russia Asia

Open Terminal and go to the project:

```bash
cd /Users/macbookofjimmy/apex4space
```

Run the importer:

```bash
.venv/bin/python time-series-api/scripts/preprocess_firms.py --input "/Users/macbookofjimmy/Documents/Russia Asia" --output-dir "time-series-api/data/areas/russia-asia/release-1"
```

The script reads all CSV files in the input folder and its subfolders,
including all dates. The output folder `release-1` must not already exist.
The folder name does not filter the data by country or continent.

Check the result:

```bash
.venv/bin/python time-series-api/scripts/check_results.py --schema2-release-dir "time-series-api/data/areas/russia-asia/release-1"
```

## Reuse the API

The API uses one selected database at a time.

1. In `time-series-api/config/settings.json`, set
   `storage.global_release_path` to `data/areas/russia-asia/release-1`.
2. Add the intended area's valid polygon and name to the area catalog.
   The catalog currently covers Viet Nam and South America. A folder named
   `russia-asia` does not add a query area. Define whether this means all of
   Russia or only its Asian part before adding the polygon.
3. Read `release_id` from the new release's `manifest.json`.
4. Start or restart the server from the project folder:

```bash
.venv/bin/python web-app/serve.py
```

Open <http://127.0.0.1:8000/docs> to try the API. Replace the values in angle
brackets below with your release ID and the name added to the catalog.
Choose dates within the new release.

Get 10 km cells for one day with `POST /v2/hotspots/query`:

```json
{
  "release_id": "<release_id>",
  "area_name": "<catalog area name>",
  "date": "2026-11-01",
  "page_size": 1000
}
```

If `has_more` is true, send the same request with `cursor` set to
`next_cursor`. Keep going until `has_more` is false.

Get daily counts with `POST /v2/hotspots/summaries/query`:

```json
{
  "release_id": "<release_id>",
  "area_name": "<catalog area name>",
  "start_date": "2026-11-01",
  "end_date": "2026-12-01"
}
```

The end date is excluded. Each summary request supports up to 366 days.
Counts are active 10 km cells, not raw detections. Zero does not prove no fire.
The web page's area choices need a separate update for new areas.
