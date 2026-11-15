# Free cloud app

Team: `thehien04s-projects`. Project: `apex4space`. Plan: Hobby.

Live site: https://apex4space.vercel.app

The small web app and Python API run on Vercel. The 313 monthly Parquet files live in one public Blob store. They use 802,362,812 bytes. The API checks each downloaded file, reads one month at a time, and removes it after use.

The same checked Parquet files are also in the GitHub repository under `time-series-api/data/areas/world/parquet-v1/monthly/` for local use. The hosted API continues to read Vercel Blob.

Chat uses exact database summaries for now. It explains hotspots, finds the busiest month in the selected range, and compares two selected ranges. Other questions receive the selected data summary. Local Ollama still works in the local app.

## Update the app

Run from `/Users/macbookofjimmy/apex4space`:

```sh
.venv/bin/python scripts/prepare_vercel.py --calendars
```

Then deploy the prepared folder:

```sh
cd /Users/macbookofjimmy/apex4space/.build/vercel
vercel deploy --scope thehien04s-projects
```

Test the new preview URL from the main project folder:

```sh
.venv/bin/python scripts/check_vercel.py https://YOUR-PREVIEW.vercel.app
```

`--calendars` is an explicit option. It saves small World and North America calendars. Matching saved calendars are reused. The default output folder is `.build/vercel`.

## Data uploads

The current files are already uploaded. To reuse the uploader after checking a new release:

```sh
cd /Users/macbookofjimmy/apex4space/.build/vercel
vercel env pull .vercel/.env.preview.local --environment preview --scope thehien04s-projects
cd /Users/macbookofjimmy/apex4space
.venv/bin/python scripts/upload_vercel_data.py --first
.venv/bin/python scripts/upload_vercel_data.py
```

The script checks local hashes. It uses four uploads at a time and keeps existing release paths. The public data prefix is `firms/<release_id>/`. Keep total stored data below 900 MB; remove old releases only after checking what uses them. The script checks the new release size, not the total size of every stored release. Do not upload a second full release alongside this one on the free store.

## Limits and settings

- Cloud pages: at most 1,000 cells. Responses: at most 2 MB.
- Data queries stop after about 50 seconds. Use a shorter range if needed.
- One monthly file stays in temporary storage at a time. SQL memory is capped at 384 MB, with 256 MB of scratch space.
- Common calendars need no Parquet download. Other queries can download whole months. One full-year query may read about 60 MB. The 10 GB free transfer allowance is finite.
- Free quotas can pause the app. No paid backend, upgrade, purchased credits or top-up was added.
- Server settings: `CURSOR_SECRET`, `FRISM_BLOB_BASE_URL`. Blob write access stays server-side.
- Hosted AI is off. Only set `FRISM_HOSTED_CHAT=1` after account verification. The code accepts only the fixed zero-price model and checks its price before calling it. It has no paid fallback.
- Cloud requests use the shared Vercel Firewall limit. The local app keeps its process rate guard. Both keep the request body limit.

## Release

The tested production build is recorded in the [release checklist](../documents/logs/2026-11-15/detail/detail-vercel-free.md).
The main site is public. Preview and unique build URLs keep Vercel sign-in protection. The shared API limit is 600 requests per minute per IP.

After those checks, stage production with `vercel deploy --prod --skip-domain --scope thehien04s-projects`, test its exact URL, then promote that deployment. A preview promotion rebuilds with production settings.

To return to a saved good production deployment:

```sh
vercel rollback https://apex4space-ciywq14b7-thehien04s-projects.vercel.app --scope thehien04s-projects
```

Check its data URL and release before rollback. Do not roll back to the first build: its map catalog response was too large.
