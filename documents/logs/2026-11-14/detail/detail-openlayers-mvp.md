# OpenLayers MVP

- [x] Reuse the checked FIRMS database and v2 endpoints.
- [x] Use static HTML, CSS, and JavaScript with one Python server.
- [x] Add named area input, UTC date, full cell count, and automatic cursor paging.
- [x] Add daily bars for the selected month; click a day to update the map.
- [x] Use EPSG:6933 and a local Natural Earth world background.
- [x] Keep the screen within the window; put extra notes in a dialog.
- [x] Bundle map dependencies locally with licenses.

Options considered: static files need no frontend build; Vite adds a build tool; React adds a component runtime. Static files were chosen for this small MVP.

Terminology: the database, release ID, v2 routes, and center inclusion rule are unchanged. OpenLayers replaces the prior Leaflet frontend choice at the user's request. `app.web.create_web_app` adds a local web shell and metadata route; it does not change database schemas or existing API payloads. Display outlines are simplified copies; API filtering keeps exact boundaries.

Validation: all static assets and `/app/config` returned 200. The mounted
app queried the full database successfully. The existing 40 tests passed.
Browser checks showed 1,083/1,083 cells for 2026-11-11 and the daily chart
selected 2026-11-01 (5,076 cells). Desktop and phone layouts use the viewport
height with no page scroll; coverage remains visible on both.

Viet Nam investigation: the database's exact polygon selects 34 cells, all
on 2023-07-12. An independent read of the supplied global sample finds 39
detections and the same 34 cells on that date. Even the wider Viet Nam
bounding box has records only on that date (66 cells). The interface now
labels counts as imported cells and describes empty dates as no matches in
the supplied files. More Viet Nam source dates are needed for a time series.
