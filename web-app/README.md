# Hotspot explorer

A single-screen OpenLayers MVP using the existing local FIRMS database.

From the repository root:

```sh
uv pip install --python .venv/bin/python -e ./time-series-api
.venv/bin/python web-app/serve.py
```

Open http://127.0.0.1:8000. The server listens only on this computer.

Choose South America or Viet Nam and any imported date. The map loads all cursor pages. Click a daily bar to change the date. The chart shows the selected month, limited to dates present in the release. Zero counts always keep the unknown-coverage notice.

The same Python process serves static files and the existing v2 API. `/app/config` supplies the selected release, date bounds, and simplified display outlines. Exact area selection still belongs to the API. No input CSV is read by a web request.

The world background is a simplified display copy of the already downloaded Natural Earth Admin-0 v5.1.1 data. Antarctica is omitted from this EPSG:6933 display. It never filters hotspots. Made with Natural Earth; data are public domain.

OpenLayers 10.11.0 and Proj4js 2.12.1 are bundled in `vendor/`, with their licenses. The app needs no CDN, tile provider, Node server, or frontend build. The local launcher creates a temporary cursor signing key unless `CURSOR_SECRET` is already set; restarting the server starts a new cursor session.

## Viet Nam data gap

The current release has Viet Nam cells on only 2023-07-12: 39 source
detections from the global sample form 34 distinct cells under the saved
center rule. There are no Viet Nam cell/day records for other dates.
This is not a usable Viet Nam history across days or months. Empty dates
mean no matching cells in the supplied files; they do not establish no fire.
Additional Viet Nam FIRMS exports are needed to build that history.
