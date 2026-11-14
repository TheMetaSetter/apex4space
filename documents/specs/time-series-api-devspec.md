# time-series-api — Development Spec

Version: 0.6 | Date: 2026-11-14 | Status: Execution in progress

This spec records the team's cell-width and daily FRP choices, the implemented
schema-1 OpenLayers pilot in §10.6, and the separately authorized all-date
schema-2 FIRMS importer and Leaflet API path in §10.7. FRP comparability and
visible Leaflet map rendering still require separate validation. Section 15
records naming and scope changes.

## 1. Goal

Build a small data service for a web app that shows fire activity over time.
The user moves around a map, draws a rectangle, chooses dates, and sees how
activity in that area compares with past years.

The service combines MODIS and VIIRS records. These sensors see different
amounts of detail, detect different sizes of fires, and pass over an area at
different times. The service must account for these differences before it
calls the combined results **harmonized**: suitable for comparison.

An API is a good boundary between the data work and the web app. Prepare and
check the data first. Let the API serve those results. The browser should not
correct satellite data or run research models.

The challenge has two phases:

1. **Phase 1 — Make the data comparable.** Collect data, test methods, check
   results, and save a numbered data release.
2. **Phase 2 — Build the web product.** Serve the checked data through this
   API and connect it to the map and calendar built by the web developer.

A **release** is a saved set of data and method settings that does not change.
A correction creates a new release. This makes old results repeatable.

## 2. Design rules

Prefer the smallest working design that is easy to read and change.

- Use one Python app and one local database for the MVP.
- Use ordinary functions, clear names, and a few short modules.
- Keep data preparation separate from API requests.
- Add a tool or layer only when it solves a measured problem.
- Keep scientific choices visible in a small settings file.
- Preserve source records. Save corrected results separately.
- Make unknown values explicit. Never turn missing data into zero.
- Record why each scientific rule exists and where it was tested.

Every change must answer: **Does this make the code harder to understand now
or harder to change later?** Prefer a simpler solution when both work. Explain
any added dependency, service, shared framework, or layer in the change note.

Do not build a general plugin system, workflow engine, task queue, ORM, or
multi-service platform for the MVP. Do not build a second database adapter
before it is needed. A small database access module is enough.

Use small batches for offline imports. Start with Python's CSV reader and
batched SQLite writes; do not load a whole archive into memory. PyArrow is
an option only if measured pilot memory or import time needs it. Neither
PyArrow nor a continuous streaming service is required by a large source
archive. Record the highest memory use, time taken, rows, and bytes for the pilot.

## 3. MVP scope and storage budget

### 3.1 Proposed starting area and years

The user's areas of interest are Viet Nam and South America. The full period
of interest is 2000–2026. Start smaller to keep downloads and local storage
small. The following are proposed starting choices, not confirmed coverage:

| Item | Starting choice |
| --- | --- |
| Historical period | 2020-01-01 through the latest available date in 2026 |
| Main area | A declared Viet Nam study area; begin with a small rectangle before expanding |
| Second area | One small test rectangle in South America, not the whole continent |
| First sensor pair | MODIS Aqua and Suomi-NPP VIIRS |
| First FRP test | A short set of matching passes in September 2026; expand to a month if storage allows |
| Calendar | Monthly values built from daily records |
| Historical comparison | At least five usable earlier years for each published comparison |

A Viet Nam bounding rectangle includes places outside the national border.
Label it as a study rectangle unless a country boundary is actually applied.
Choose and save the exact rectangles after a small data-size check.

Use complete years from 2020–2025 where they are available. In 2026, stop at
the source's actual data cutoff. Do not invent data through year-end.
The full 2000–2026 record and wider areas are later work.

### 3.2 Keep local data small

Proposed budgets:

- Keep the saved MVP data, database, and reports within **500 MiB**.
- Allow at most **2 GiB** of temporary download space.
- These are budgets to test, not claims about the actual source sizes.

Download a small sample first. Measure rows and bytes by source and year.
Estimate the full size before starting a larger download. Stop before a disk
budget is exceeded and show which files or windows are still missing.

Keep compact hotspot rows, daily results, small coverage summaries, source
file records, and test reports locally. Download large native satellite files
one small batch at a time. Keep only the needed area and fields after checking
the output. Remove temporary downloads only after their results, source IDs,
checksums, and processing settings have been saved.

If the same data would be copied into both CSV and the database, keep one
main copy where possible. Keep a small source sample for tests. Downloaded
native files that are removed must remain traceable and possible to fetch
again. Never delete unrelated user files.

If the budget is too small, reduce area first, then years. Keep at least five
usable historical years where a historical comparison is offered. If this is
not possible, return no historical comparison rather than a misleading one.
Do not reduce scientific checks merely to fit the budget.

**Chosen first input path:** download and save a small FIRMS API sample.
Start with one declared rectangle, Aqua and Suomi source selections, and one
1–5-day window within their verified overlap. Save source bytes temporarily,
their hashes, and the exact request parameters without the key; import the
checked records into SQLite. The API then reads these saved records. No
provider request is needed to reopen a query. Extend dates only after this
path works and measured budgets allow it. Native coverage inputs remain
required for scientific checks. A short hotspot sample supports an API demo,
not a validated historical or harmonized result.

If the API cannot provide that shared window, save an available source-only
sample for web development and list the missing test inputs. Do not silently
switch sensors or reuse a method tested on a different pair.

Existing Drive archives are optional inputs, not a prerequisite. Their four
CSV sizes total 6,789,878,153 bytes (about 6.32 GiB) [R13], beyond the temporary
budget even before database writes. Prefer new small-area downloads; if an
archive is used, read small batches from an accessible source and keep
only the selected area/dates. Do not download all archives or unpack all ZIPs
to make the first pilot. ZIP and extracted files are not independent evidence.

### 3.3 What the MVP includes

- A map query for any rectangle fully inside a prepared study area.
- Source hotspot points and checked, comparable count estimates.
- A calendar, historical median, differences from that median, and coverage.
- CSV downloads of source detections and JSON downloads of analysis results.
- Clear data dates, source names, method versions, and missing-data labels.
- An API guide and examples for the web developer.

Predicting fire spread, evacuation routes, dispatching teams, burned area,
and counting separate real fire incidents are outside this MVP. Brightness
prediction for five bands is optional research, not a required step.

Fire-event clustering, wildfire probability, economic loss, and automated
severity alerts are also outside this MVP. Historical differences describe
selected detections; they do not estimate a country's probability of fire.
NASA's download guidance advises against local emergency decisions from
these data [R15]. Show that limitation with source credits in the web product.

## 4. User workflow

1. Move and zoom the map.
2. Turn on **Select area**, then drag a rectangle.
3. Choose the dates and apply the selection.
4. Read the activity summary and calendar.
5. Click a month or day to inspect source hotspot points.
6. Compare recent activity with the same time window in past years.
7. Download the selected data or analysis.

The team has chosen **OpenLayers** for `web-app/`. The API keeps its ordinary
JSON/GeoJSON contract. The frontend sends the analysis request when drawing ends or
when the user applies filters, not on every mouse move. It must ignore old
responses after the user changes the selection.

The web developer owns the map, drawing tools, charts, colors, loading states,
and download buttons. This project owns data preparation, calculations,
source tracking, and API results. A working API alone does not complete the
challenge; the map and calendar must also work with it.

## 5. User stories

| ID | User story | What must work |
| --- | --- | --- |
| ER-01 | As an emergency responder, I want to select my area and recent dates so I can see detected activity. | Map and summary use the same area, dates, and release. Show the latest observation and data update times. |
| ER-02 | As an emergency responder, I want to compare this month with past years so I can spot unusual activity. | Compare the same days of the month. Show the years used and whether observations were good enough. |
| ER-03 | As an emergency responder, I want to tell low activity from poor observation so I know when more monitoring may be needed. | Zero detections, missing observations, low coverage, and old data have different labels. |
| ER-04 | As an emergency responder, I want to download results for a briefing. | Downloads match the screen and include dates, units, data version, and source notes. |
| SC-01 | As a scientist, I want original and corrected series so I can judge the method. | Both are available; estimated values never replace source measurements. |
| SC-02 | As a scientist, I want the data sources and method settings so I can repeat the analysis. | Each result links to a release record with source IDs, file hashes, code version, settings, and test report. |
| SC-03 | As a scientist, I want coverage and error information so I can judge the result. | Each period has quality information. If an error range is not available, say so. |
| LM-01 | As a land manager, I want a monthly calendar over several years so I can find common fire seasons. | Every requested month appears, including months with missing data. Use the same count definition throughout. |
| LM-02 | As a land manager, I want to compare periods in the same area so I can review changes. | Keep the area, units, method, and coverage rules the same. |
| LM-03 | As a land manager, I want to reopen the same query later. | The frontend can save area, dates, metric, and release in its URL. User accounts are not needed for the MVP. |
| WD-01 | As a web developer, I want clear API examples so I can build the interface. | Supply OpenAPI documentation, example requests, and test responses for normal, missing, zero, and error cases. Mark invented examples as test data. |

## 6. Terms and limits

| Term | Simple meaning |
| --- | --- |
| Hotspot (hotspot cell) | A grid cell with selected source detections on one UTC day. It is not a separate wildfire. |
| Source detection | One satellite point record. The existing point API keeps its field names. |
| FRP | Fire radiative power: estimated power from fire inside a pixel, in megawatts (MW). |
| Pixel | The ground area represented by one sensor reading. |
| Coverage | How much of the expected area and passes had usable observations. |
| Pass | One satellite visit over the area. |
| Baseline | Earlier years used for comparison. The default is their median: the middle value after sorting. |
| Harmonized count | An estimated count under one stated sensor and observation rule. It can be a decimal. |
| Release | A saved, fixed version of data, settings, and results. |

The paper's observation operator describes how FRP may be detected by a sensor
[R2]. It does not by itself make hotspot counts comparable or convert one
brightness band into another.

The source code can randomly keep or reject a detection using its detection
probability. When kept, its input FRP stays the same [R3]. A probability-weighted
FRP is not a new measured fire power. Do not use it as such to calculate a
temperature. Save any random results with their seed so API requests give
repeatable answers.

Equal FRP totals do not prove equal hotspot counts. A shared grid does not
solve all sensor differences. The method cannot uniquely recover every small
fire that MODIS missed in the past.

## 7. Data to prepare before the MVP

### 7.1 Files already checked

The four NRT CSV files below were read and checked on 2026-11-13. NRT means
near real-time; these recent records may later be revised.

| File | Rows | Observation dates |
| --- | ---: | --- |
| `fire_nrt_M-C61_842795.csv` | 164527 | 2026-09-01–2026-11-11 |
| `fire_nrt_SV-C2_842798.csv` | 764484 | 2026-08-01–2026-11-02 |
| `fire_nrt_J1V-C2_842796.csv` | 830112 | 2026-08-01–2026-11-11 |
| `fire_nrt_J2V-C2_842797.csv` | 800041 | 2026-08-01–2026-11-11 |

They share these fields:

```text
latitude, longitude, brightness, scan, track, acq_date,
acq_time, satellite, instrument, confidence, version,
bright_t31, frp, daynight
```

No blank values or fully repeated rows were found. That does not prove every
measurement is valid or rule out repeated views of the same place.
Four archive CSVs were found but their contents could not be read. Their
fields and years still need checking.

The linked `modis-viirs-eda.ipynb` was reviewed for v0.4 [R13]. Its saved
MODIS and NOAA-21 samples include `type`; its MODIS output contains both
`6.03` and `61.03` version values. These are saved notebook outputs, not a
fresh scan or a verified collection mapping. The full archives were not read
in this revision. Do not infer complete years, area coverage, or product
identity from a folder name or a few sample rows.

There is a source-date conflict to resolve before using NOAA-21: the notebook
shows March 2023 records, while the FIRMS field page currently lists its
coverage from 17 January 2024 [R6]. Also, that page currently lists Suomi
coverage through 2 November 2026. Record these as provider/product coverage
claims, not satellite lifetime claims. Check the actual chosen product and
availability before downloading, fitting, or substituting another platform.

These files do not include M13, background readings, or full coverage and
quality maps. Suomi rows may say `instrument=SNPP`; map this to `VIIRS` and
keep the original text. Many VIIRS I4 readings equal 367 K, a value that needs
special treatment because the sensor can reach its measurement limit [R4].

### 7.2 Required data checklist

| Data | Why it is needed | Ready when |
| --- | --- | --- |
| Small-area historical MODIS and VIIRS hotspot rows | Build the calendar and compare years | Years, area, fields, file hashes, and source dates are checked. |
| At least five usable earlier years | Build a historical median | Each published month has enough valid same-window comparisons. Current NRT files alone are not enough. |
| MODIS Aqua MYD14 fire data and MYD35 cloud/quality data | Run the first FRP test | Matching files and their product versions and positions are checked. |
| Suomi VNP14IMG fire data and VNP03IMG location data, including masks and QA | Run the first FRP test | Fire, non-fire, cloud, missing, and other quality states are available. |
| Pass times, pixel areas, and usable-area maps | Compare observation conditions | Missing visits can be separated from visits with no detections. |
| Saved study rectangles and grid | Repeat area calculations | Coordinates, cell width in km, equal-area projection, origin, edge rule, and grid version are recorded. `w` is the cell width; test a small value before widening the study area. |
| Rules for sources and repeated records | Avoid double counting | State which sensor, pass, product, and record takes priority. |
| Separate training and test periods/areas | Check the method fairly | Related observations stay together; final tests are set aside before tuning. |
| Small sample and test responses | Help the web developer | Include available, zero, missing, partial, old-data, and unsupported cases. |
| Release record and test report | Serve checked results | All required data and method checks pass. |

QA means the quality flags supplied with a satellite product. A mask is a map
that labels each pixel, for example as cloud, fire, or missing.
M13 is not required for this MVP. If the optional band-prediction study is
added, fetch matching VIIRS M-band Level-1B data and its conversion tables.
`FP_Rad13` is radiation measured in radiance units, not Kelvin [R4, R5].

### 7.3 Cleaning rules

- Read dates and zero-padded HHMM times in UTC. For example, `1` means `0001`.
- Keep the original file ID, row ID, satellite, product version, and pass ID.
- Prefer standard processed data over NRT for the same observation. Keep a
  record of what was replaced. Do not remove real neighboring pixels.
- Keep zero FRP records until quality flags explain them. Zero FRP does not
  always mean no fire [R4].
- Keep confidence in its source form. MODIS scores and VIIRS labels are not
  equal probabilities.
- Use `scan * track` as an approximate pixel area only when better geometry is
  unavailable. Record that choice. M13 has its own pixel size.
- Map VIIRS `bright_ti4` and `bright_ti5`, or verified export aliases, to explicit
  band names. Do not identify a band from a shared column name alone.
- Keep hotspot source type where available. Otherwise use `unknown`, not
  `vegetation_fire`.
- Check new satellites and product versions before reusing fitted settings.

### 7.4 Shared cells and daily FRP

The team chose a grid of square cells with side length `w` km in a fixed
equal-area map projection. `w` is a distance, not the number of rows or
columns. Record `w`, the projection, grid origin, cell ID rule, and grid
version in each release. The exact projection and edge rule must be frozen
in T9. Do not use degree squares as equal-area cells.

Assign a detection to the one cell that contains its center. A cell is a
hotspot for a UTC day when either sensor has one or more selected detections
in it. Keep detection counts and presence by platform separate. A missing
detection is not a clear cell unless coverage data show a usable visit with no
detection.

For each cell, platform, and satellite pass, sum valid raw FRP in MW. Keep
each record's original FRP unchanged. The daily value for one cell and one
platform is the highest valid per-pass cell sum in that UTC day. Do not add
different passes. This is an observed daily peak, not energy emitted over the
day. Report zero only when usable coverage confirms a visit with no detected
FRP. If usable coverage is unknown, report an unknown value, not zero.

Keep MODIS and VIIRS daily values separate until a comparison method passes
tests on held-out dates and areas. Do not average or add their values. For the
first comparison, measure raw differences for paired, near-time passes over
the same cells and valid coverage. Then test one simple scale factor fitted
on tuning data. Keep it only if it improves held-out results. A grid alone
does not make the sensors comparable.

Read `version`, confidence labels, and source IDs as text. Resolve platform
aliases through a documented source/product mapping and retain their original
values. Unknown aliases or mixed, unexplained product versions block their
use in harmonized results; do not guess a mapping from a numeric conversion.

The MVP counts selected **thermal detections**, not confirmed wildfires.
Preserve `type`: presumed vegetation fire, volcano, other static land source,
offshore, or unknown according to the actual product definition [R6]. Freeze
the type/confidence selection policy in each release and apply it consistently
to points, totals, history, and exports. Start with all types, visibly labeled;
vegetation-only comparisons need comparable type information across sources
and years before publication. Unknown type must not become vegetation fire.
Do not convert confidence scores/labels into a shared probability or a
severity rating without a separate calibration study.

## 8. NASA FIRMS downloads and transaction budget

Use the official tutorial and endpoint pages [R7–R9]. NASA supplies source
data. This project adds the comparison method and the API for the web app.

### 8.1 Key and limits

The key limit is **5,000 transactions per 10 minutes**. One HTTP request can
use more than one transaction. Retries and status checks must also fit the
budget; do not assume 500 requests per minute is always safe.

- Read the local key as `FIRMS_MAP_KEY` from the repository `.env` or the
  process environment. The environment takes priority. Do not commit or log
  the key. `MAP_KEY` in NASA endpoint paths below is the provider placeholder.
- For this implementation, make no more than five FIRMS API requests in
  total. Count status, availability, and data requests. Check the provider's
  transaction budget before data requests; one request can cost more than one
  transaction.
- Never send it to the browser or print full URLs containing it in logs.
- Read the key-status response to track actual use and the reported limit.
- Start with one download at a time.
- Proposed safety rule: pause ordinary downloads at **4,000 transactions in
  the current provider window**, leaving 1,000 for shared use and other work.
- This safety rule assumes the remaining use is bounded; it is not a guarantee
  if another program uses the same key. Check use again before each batch.
- Resume after the provider window allows it, using provider status or retry
  guidance. Save progress rather than repeatedly making rejected requests.
- If status is unknown or the shared-key budget is unclear, pause.

Keep these limits in one settings file. The NASA limit and the proposed
safety margin are different: 5,000 is the stated limit; 4,000 is our default.
A request can consume more than the remaining margin, so split large jobs
into small windows and check their measured cost before scaling up.

### 8.2 What to request

First call `data_availability` to check the actual sources and date ranges.
Do not use dates printed in a tutorial example as today's availability.
Then request fixed source, area, and date windows:

```text
/api/data_availability/csv/{MAP_KEY}/ALL
/api/area/csv/{MAP_KEY}/{SOURCE}/{BBOX}/{DAY_RANGE}/{DATE}
```

`BBOX` is `west,south,east,north`. The area documentation checked on
2026-11-13 allows 1–5 days per request [R8]. Split longer periods into windows
of at most five days. With an explicit DATE, NASA includes DATE through
DATE + DAY_RANGE - 1. Translate this carefully to our API's exclusive end date.
Recheck provider limits before implementing the loader.

Use standard processing for historical data where available. Treat recent
NRT results as provisional. Check whether standard data later replace them
and publish a new release. Filter MODIS rows to Aqua for the first test.
Check current source lists rather than assuming the tutorial is complete.

The frontend must query our local prepared data. A user dragging the map must
not trigger repeated NASA downloads. Bulk files may be better for long
historical downloads, but check their size before fetching them.

### 8.3 Failures and source limits

Use timeouts, a small retry limit, and longer waits after repeated failures.
Save completed windows so downloads can resume. Follow provider retry advice.
Check HTTP status, CSV fields, and requested dates before accepting a file.
An error page is not an empty hotspot result.

Source date availability does not show whether a specific area was clear of
cloud. FIRMS hotspot CSVs do not replace the native quality and coverage data
needed for the FRP test. The country endpoint is optional; NASA notes that
large, complex country queries can time out.

No request using a project MAP_KEY has been run while writing this spec.

## 9. Phase 1 — Make the data comparable

### Step A: prepare a small, checked sample

Choose the exact rectangles, estimate download size, and list missing inputs.
Load a small Aqua–Suomi sample and its coverage data. Save source records,
quality flags, and fixed test splits. Use a short set of passes before a full
month. Measure both disk use and NASA transaction cost.

**Output:** cleaned sample, source list, coverage table, and test settings.

### Step B: test the FRP observation operator

Match the nearest actual visits over the same ground area. Try time gaps of
15, 30, 60, and 120 minutes as test settings, not as claims of equal times.
Put source detections onto the other sensor's observed ground areas. Account
for clouds, missing pixels, repeated views, pixel size, and day/night.

Begin with explicit time and ground-footprint matching rules. A match is a
candidate association, not proof of one real fire. Allow multiple small
pixels to overlap one larger pixel. Keep unmatched detections and report
their amounts by sensor and observation conditions; do not label them false
alarms or delete them because the other sensor has no match. Save matching
settings and associations in the offline evaluation report as needed.

Follow the paper's two-way comparison [R2, Section 3.5]:

\[
\Xi_{\mathrm{MODIS}}(P_{\mathrm{VIIRS}})
\quad\mathrm{vs.}\quad
\Xi_{\mathrm{VIIRS}}(P_{\mathrm{MODIS}}).
\]

Here, P is FRP and Xi is the observation operator for the named sensor.
Compare three cases: original data, matched coverage only, and matched
coverage plus the operator. Check average signed error, mean absolute error
(MAE) in MW, and error ranges. Report results by fire power, day/night,
pixel size, and time gap. Handle zero comparison totals separately.

Check the chosen code version against the paper before use. Save random
seeds, repeat counts, and variation across repeats when using random draws.
Do not run new random draws for each web request.

For the cell FRP comparison, first sum valid source FRP by cell and pass,
without a correction. Compare MODIS and VIIRS only for paired passes with
matching usable ground area and the chosen time gap. Report the raw signed
difference and MAE. Then test one scale factor fitted only on tuning data.
Report its held-out result beside the uncorrected result. Keep daily peaks
separate by platform. Do not publish one combined FRP value unless the
correction passes the independent test.

**Pass condition:** results improve on data held out from tuning, without
large unexplained failures in important groups. If not, change the method.
Do not force two totals to match by design.

### Step C: test a common hotspot count

FRP agreement does not solve hotspot counting. This step needs its own test.

Proposed target: the number of detections expected under one fixed
MODIS Aqua-like observation rule. State the ground area, visit schedule,
quality rules, and sensor used as the reference. Keep that target the same
across all years.

Compare these simple choices:

1. Group/project VIIRS detections onto reference observation areas, then apply
   declared detection and coverage rules before counting.
2. Fit a simple count model from source counts, FRP summaries, coverage,
   season, and pass counts to reference counts. Use only inputs that will
   exist when the model is used.
3. Keep matched but uncorrected counts as the baseline to beat.

Choose the simplest method that passes independent tests. A 1 km grid alone
is not the method. Do not add all sensors' detections together and call the
result a count of separate fires.

Test on different dates and areas. Keep related pixels together, including
VIIRS pixels sharing FRP from a larger pixel [R4]. Include low-activity days.
Check count error, seasonal patterns, and false jumps when the source changes.

Write pass/fail targets before fitting. Proposed starting targets: total count
bias within 10%, lower count MAE than the uncorrected baseline, and no meaningful
loss of seasonal agreement on held-out data. Define how seasonal agreement
is measured before running the final test. These are project targets, not
known sensor accuracy. Report failures and error ranges honestly.

**Output:** a clear count definition, chosen method, test report, and the exact
areas, years, seasons, satellites, and products where it passed.

For each tested approach, record what it solved, what failed, and the next
useful test. Start with declared rules; consider a fitted method only when
its independent improvement justifies the added work. DBSCAN, graph clustering,
and neural models are not prerequisites for this count target. If later work
groups detections into events, it needs its own event definition and evidence
for false merges, false splits, missed events, and processing delay. Matching
for a count study does not establish an operational event detector.

### Step D: prepare the historical release

Expand from the sample to the prepared areas and 2020–2026 window, within the
storage budget. Test on additional years before serving historical comparisons.
Check Terra, NOAA-20, and NOAA-21 separately before adding them. Do not assume
a method tested on Suomi works for every satellite or changed orbit.

Save a fixed release with sources, file hashes, code version, settings, and
supported metrics. Mark estimates outside the tested range as unavailable.
If count tests fail, serve only original data and clearly labeled research
results. That is useful for development but is not a finished harmonized MVP.

## 10. Data tables and calculation rules

### 10.1 Existing six-table design

These are the existing tables. Section 10.6 proposes a smaller map and daily
count path. Existing science tables keep their meanings and data.

| Table | What it stores |
| --- | --- |
| `source_file` | Source/file IDs, product, version, dates, download time, processing mode, and SHA-256 file hash. |
| `observation` | Source row and pass IDs, satellite, UTC time, longitude, latitude, pixel sizes, FRP, original confidence, quality, and hotspot type. |
| `band_measurement` | Observation ID, actual band or composite band name, value, unit, and measurement-limit/quality flag. |
| `opportunity` | Pass ID, time, covered area, usable area, expected visit information, and quality state. |
| `analysis_daily` | Release/method/cell/date, source count, reference count estimate, coverage amounts, error information, and status. Cell FRP values remain source-specific until their storage and API contract are reviewed. |
| `release` | Fixed data/code/settings versions, source cutoff, tested areas/dates, baseline rules, and available metrics. |

A native satellite file is a **granule**, or short segment of a satellite
visit. Keep its ID when available. A file hash checks that its bytes have
not changed. Do not silently treat MODIS 21/22 as a known individual band
unless the source gives that information.

### 10.2 Metrics

| API metric | Unit and meaning |
| --- | --- |
| `observed_hotspot_count` | Integer count of selected source detections after stated duplicate handling. |
| `harmonized_hotspot_count` | Nonnegative estimated reference detections; decimals are allowed. Requires passed count tests. |
| `active_cell_count` | Required daily hotspot count for the planned cell analysis: distinct detected cells in the selected area, UTC day, release, and platform selection. Count a cell once across platforms. Existing point/count API fields keep their meanings. |
| `frp_pass_sum_mw` | FRP summed over a stated area for one pass. Sums over many times are not emitted energy. |
| Daily cell FRP (planned) | Highest valid per-pass cell FRP sum in one UTC day, reported separately for each platform. This is an observed peak in MW, not daily energy or a corrected MODIS–VIIRS total. It is not in the current API contract. |
| `valid_coverage_fraction` | Usable area across scheduled visits divided by expected area across those visits; null if unknown. |

Use UTC dates for the MVP. Local-day calendars can be added later.
For a monthly result, use only the requested days within that month. A query
for November 1–13 does not ask for a complete November total.

Show expected and usable days. If a required day lacks a valid estimate,
return `value=null`; an explicit `partial_value` may show the known part.
Do not fill gaps or divide by coverage unless that rule was tested as part
of the method. A partial calendar month can still have complete observations
for all requested days; label these two facts separately.

Proposed daily coverage threshold: 80% usable scheduled area-visits. Test and
save this setting. Enough coverage does not itself correct different numbers
of visits. The reference visit schedule must handle that separately.

### 10.3 Historical comparison

Use the same area, metric, method, release, and calendar-day window across
years. Use at least five usable earlier years and exclude the target year.
List the years used and reasons for exclusion.

Compare month-to-date with the same days in previous years, not full months.
Use the same month/day window for other partial-month queries. Exclude
February 29 from cross-year comparisons in the MVP.

Return the historical median, absolute difference, and percentage difference.
If the median is zero, return a null percentage with `ZERO_BASELINE`.
A historical rank is a description of past data, not a forecast or emergency
severity rating. Require enough baseline years before returning that rank.

If error ranges are available, name how they were calculated. The proposed
method repeatedly resamples related areas/events/dates together (block
bootstrap), then calculates each requested total within each repeat.
Do not add interval endpoints or treat related observations as independent.
Until implemented and checked, return `uncertainty=null` and
`UNCERTAINTY_UNAVAILABLE`. Past-year variation and model error are different.

### 10.4 Area boundaries

Count source points inside the requested rectangle. For cell-based estimates,
include whole cells whose center lies inside it. Do not split an estimated
count by cell area without a tested rule.

Return both the requested rectangle and the area actually used for cell
results. If no cell center falls inside a small selection, return
`INSUFFICIENT_SPATIAL_SUPPORT`, not zero activity.

### 10.5 Allow for polygon selections later

Rectangles are enough for the MVP. Later, responders may draw an irregular
area in OpenLayers. Keep area-selection rules together so this can be added
without changing the scientific method or adding a new service.

Internally, convert the requested rectangle to a GeoJSON Polygon. A bounding
box can narrow database reads, but a future polygon query must then test the
actual shape. Never return the surrounding rectangle as the polygon's result.
Source points must lie in the selected shape; estimated cells must have their
centers in it. Use that same shape for coverage, history, paging, and exports.
Keep the existing whole-cell rule and return the area actually used.

A future API revision may accept exactly one of `bbox` or `geometry`, while
keeping existing rectangle requests valid. Polygon support needs its own
input checks and tests: coordinate order, closed rings, holes, invalid or
self-crossing shapes, boundary points, and limits on vertices and area.
Reject shapes outside the prepared release; do not silently trim them.
Check the full shape in cursor/query matching. OpenLayers sends geographic
coordinates, not map-screen coordinates. No polygon request field, geometry
library, or polygon-drawing feature is required for the MVP.

### 10.6 Hotspot cell schema and pilot implementation — 2026-11-14

Status: the processed-only schema-1 path is implemented and a separate local
pilot was published and checked. This section records that pilot only; §10.7
defines the later all-date schema-2 release. It does not replace the legacy
database or validate broader science work.

#### Two small processed tables

| Table | Primary key | Fields |
| --- | --- | --- |
| `hotspot_cell` | `(grid_version, cell_id)` | `center_longitude`, `center_latitude`, full GeoJSON `geometry`. Store only cells detected in the prepared releases; save each shape once per grid version. |
| `daily_hotspot_summary` | `(release_id, area_id, date)` | Nullable `active_cell_count`, nullable sorted unique `hotspot_cell_ids` as JSON, `status`. One row per prepared area and UTC day. |

Do not create `cell_detection` or any raw observation table in the new dataset.
No raw rows, FRP arrays, band values, or detection-to-cell links are retained
locally after preprocessing. Keep only the processed cell/day sets and shapes.
Original CSVs remain in the user-provided local input folder; preprocessing
does not copy them into the processed dataset. Existing user files and the
legacy database are not deleted by this work.

Source identities, versions, full hashes, selected dates/platforms, area/catalog
hash, grid settings, code version, and completeness checks stay in small
`manifest.json` and `validation.json` files. Store filter rules and counts,
not lists of original row IDs or raw records. The area catalog remains a
versioned local file. These are metadata files, not additional database tables.
Validate metadata and processed-data hashes before serving a release.

#### Streaming preparation

Input: exact relative CSV paths selected in
time-series-api/config/processed-settings.json from the user-provided local
FIRMS directory. This execution does not use the Google Drive API or make
FIRMS network requests. The pilot allowlist selects only the MODIS Terra/Aqua
NRT 2026 file and VIIRS Suomi-NPP NRT 2026 file; ZIPs, notebooks, archive CSVs,
other sensors, and dates are not read.

1. Stream bytes in small chunks; parse and check one CSV batch at a time.
2. Convert each selected detection's center to its fixed grid cell.
3. If the cell center is inside the prepared area, add its ID to that UTC
   day's set. This includes detections outside the area outline when their
   full cell is selected. Discard the raw row after this step.
4. Verify EOF, complete byte count, full SHA-256, unchanged local file
   identity, and consistent source version. A failed or capped stream must
   not produce a published release.
5. Union the selected files' daily sets. A cell seen by several platforms or
   passes counts once per day. Build shapes only for the union of active cells.
6. Save each day's sorted unique IDs, their count, and status. Publish both
   tables and checked metadata as one release. Keep no temporary raw-row file.

Aqua seeing A/B and Suomi-NPP seeing B/C gives three hotspots, not four.
A cell active on two days counts once on each day. Summed daily counts are
cell-days, not unique cells over the entire period.

Save every day in the declared period. A processed empty input day has `[]`
and count 0 with an explicit coverage state. Missing input has null IDs and
null count; partial input retains only its known set and `partial` status.
No detection does not prove no fire or usable observation coverage.

#### Web read path

**Flow:** Website → API → `daily_hotspot_summary` → `hotspot_cell` shapes →
GeoJSON features + daily hotspot count → OpenLayers map and count display.

For a named area/day, read the saved summary and its shapes. The release
manifest fixes the grid version. Return one GeoJSON feature per listed cell.
Do not query Drive, raw sources, or a detection table during a web request.

For a bbox fully inside a prepared summary area, filter its listed cells by
center and count the retained IDs. Do not return the unfiltered area's total.
Reject selections without a containing prepared area. Clip display shapes only;
keep full cell IDs. GeoJSON uses longitude/latitude; OpenLayers transforms it
into the view projection. Keep the basemap below hotspot shapes.

Use one grid width `w` in km per release. A width change creates a new grid
version/release. Save published releases within budget; pause publication if full.
A different platform filter requires a separately prepared release. Raw detail,
FRP comparison, and history validation are outside this processed-only MVP.

#### Size, integrity, and compatibility

- Store geometry once, not once per area/day. Keep compact IDs and JSON.
- Bound distinct cell/day memberships at 100,000 per run and cells at 10,000
  per map response. This replaces the old retained-raw-row cap on this path.
- Saved data remain within 500 MiB; temporary data within 2 GiB. Measure the
  pilot. These bounds are limits, not a guarantee that every requested area fits.
- Count equals unique ID-list length. Every listed ID must resolve in the
  manifest's grid. JSON-list references are checked during preprocessing;
  they are not SQL foreign keys. Missing shapes make a release invalid.
- Use a separate pilot database with exactly these two user tables. Do not
  run the old six-table initializer or copy the old science tables into it.
- Existing point/raw export routes remain for legacy releases. On a processed
  release, return an explicit unsupported-dataset/metric error; do not invent
  points or silently fetch Drive. Existing user databases remain untouched.

#### TimescaleDB later

Start with SQLite. If needed, move both tables to regular PostgreSQL tables
first and compare results. `daily_hotspot_summary` is the first hypertable
candidate: its key includes `date`. If partitioning by a new UTC timestamp,
migrate the day column and key together. Keep geometry in a regular table.
No time-series server or automatic retention job is needed now.

For much larger areas or years, repeated JSON ID lists may outgrow the budget.
This warning applies to schema 1 only. Schema 2 in §10.7 uses a normalized
cell/day table. Reprocessing still requires the original local CSVs; the
schema-1 pilot does not guarantee that an older remote source remains available.

### 10.7 All-date FIRMS release and named-area queries — schema 2

Status: execution authorized on 2026-11-14. Build a separate, portable
database from arbitrary user-selected FIRMS CSV files. Do not mutate the
schema-1 pilot database or change its v1 route. The user approved the compact
third processed table and requested every valid input row and acquisition date.

#### Input and row accounting

The standalone `scripts/preprocess_firms.py` accepts repeated `--input`
arguments, each naming a CSV or recursively searched directory. Match `.csv`
case-insensitively, sort and deduplicate canonical paths, and do not interpret
filenames. Require normalized unique `latitude`, `longitude`, and `acq_date`
headers. FIRMS CSV coordinates are geographic longitude/latitude in
EPSG:4326; the files do not embed a CRS. NASA's CSV tutorial constructs
geographic points in EPSG:4326. [NASA FIRMS visualization tutorial](https://firms.modaps.eosdis.nasa.gov/content/academy/data_visualization/firms_visualization.html)

Read UTF-8/BOM CSV with strict row widths and bounded fields. Support quoted
newlines and a missing final newline. Validate finite WGS84 coordinates,
ISO date, and UTC acquisition time when present. Other FIRMS fields are
optional provenance; unused brightness/channel names do not determine
eligibility. A malformed required value or changed source fails the complete
build with a file and record number. Never log raw rows or publish a partial
database. All sensors, confidence classes, versions, dates, and hotspot types
are included. No remote FIRMS or Google Drive request is made.

Each valid source row increments its assigned-row count and contributes a
`(release_id, date, grid_version, cell_id)` key. Duplicate keys across files,
passes, sensors, or archive/NRT copies collapse to one membership. Distinct
cells remain. `rows_read` must equal `rows_assigned`; invalid rows abort rather
than being skipped. Record file paths, byte counts, full hashes, compact
source labels, software/PROJ versions, and counts in release metadata, never
raw input attributes.

#### Schema-2 grids and database

Use grid versions `firms-ease-global-10km-v2` (EPSG:6933),
`firms-ease-north-10km-v2` (EPSG:6931), and
`firms-ease-south-10km-v2` (EPSG:6932). Each uses a custom 10,000 m square
lattice, origin `(0,0)`, integer floor
indices, and half-open edges. Snap a projected coordinate within 1e-6 m of an
integer lattice line to that line before `floor`; the exact edge belongs to
the cell to its east/north. Canonicalize longitude +180° to −180° before
projection. Transform with `always_xy=True`. Grid ownership
is deterministic: EPSG:6933 owns latitude −86° through +86° inclusive;
EPSG:6931 owns latitude greater than +86°; EPSG:6932 owns latitude less than
−86°. These are custom cell lattices, not claims of native NSIDC pixel
alignment. NSIDC identifies EPSG:6931/6932 as the northern/southern polar
EASE-Grid projections and EPSG:6933 as global/temperate equal-area. [NSIDC, A Guide to EASE Grids](https://nsidc.org/data/user-resources/help-center/guide-ease-grids)

`grid_version` is part of every cell key, so projected indices in different
CRSs cannot collide. Canonicalize the ±180° seam, densify inverse-projected
edges to at most 1,000 m between samples, normalize geometry order, validate
finite coordinates, split antimeridian geometries, and clip EPSG:6933 geometry
to its geographic validity domain. Preserve every valid
polar row under the supplemental grids. An EPSG:6933 map cannot validly show
the complete polar bands; APIs expose each feature's grid version and warn
when polar features are outside that view.

The schema-2 SQLite database contains exactly these three user tables:

| Table | Primary key | Stored values |
| --- | --- | --- |
| `hotspot_cell` | `(grid_version, cell_id)` | Grid row/column, projected bounds, WGS84 center, and full GeoJSON cell geometry. |
| `hotspot_cell_day` | `(release_id, date, grid_version, cell_id)` | Compact unique membership with foreign keys to cell geometry and global day. |
| `daily_hotspot_summary` | `(release_id, date)` | `area_id='world'`, distinct global cell count, `coverage_unknown`, and `input_state`. |

Use these exact fields. `hotspot_cell` stores `grid_version TEXT`,
`cell_id TEXT`, `column_index INTEGER`, `row_index INTEGER`, `min_x_m REAL`,
`min_y_m REAL`, `max_x_m REAL`, `max_y_m REAL`, `center_longitude REAL`,
`center_latitude REAL`, and canonical `geometry_json TEXT`. Require finite
numbers, ordered bounds, and a cell ID matching the two integer indices.
`daily_hotspot_summary` stores `release_id TEXT`, ISO `date TEXT`,
`area_id TEXT CHECK(area_id='world')`, nonnegative `active_cell_count INTEGER`,
`status TEXT CHECK(status='coverage_unknown')`, and
`input_state TEXT CHECK(input_state IN ('records_present','no_records'))`.
`hotspot_cell_day` stores only `release_id`, ISO `date`, `grid_version`, and
`cell_id`, all `NOT NULL`. Enforce its primary key and both foreign keys.
Use `WITHOUT ROWID` for all three tables; geometry remains
one row per unique active cell and raw CSV attributes are absent.

Logical table hashes use UTF-8 canonical JSON arrays with compact separators,
`ensure_ascii=False`, and `allow_nan=False`; array fields follow each table's
column order above. Begin each table digest with domain bytes
`apex4space.firms.logical.v1\0`, UTF-8 table name plus NUL, and row count as
an unsigned 64-bit big-endian integer. Stream rows in primary-key order;
before each row's JSON bytes, hash its byte length as an unsigned 64-bit
big-endian integer. The `logical_sha256` is SHA-256 of canonical UTF-8 JSON
(`sort_keys=True`, compact separators, `ensure_ascii=False`, `allow_nan=False`)
with exactly `hash_version`, `schema_version`, `grid_policy_version`,
`reduction_policy_version`, and sorted `tables` entries `{name, rows, sha256}`.
This avoids materializing a release-sized list. Store the encoding version
beside every digest.

Accept only canonical Gregorian `YYYY-MM-DD` dates. Optional `acq_time` is
four decimal UTC digits `0000`..`2359`; validate it but derive the date only
from `acq_date`. Invalid required coordinates/date/time, duplicate normalized
headers, ragged rows, or a changed/unreadable source abort the entire build.
Never skip invalid rows. Days without rows inside the imported date range
store count zero, `coverage_unknown`, and `no_records`; days with rows store
`coverage_unknown` and `records_present`.

Use exactly two secondary indexes: `(grid_version, cell_id, release_id, date)`
on `hotspot_cell_day`, and `(center_longitude, center_latitude, grid_version,
cell_id)` on `hotspot_cell` for bbox candidates. Do not store cell-ID JSON arrays or
raw detections. Do not add default R-tree virtual tables. Every date between
the minimum and maximum observed acquisition date has a global summary. A
zero-count day has `input_state='no_records'` and `coverage_unknown`; zero is
not evidence of no fire or complete observation coverage. Dates outside the
imported range return an explicit unavailable-date error.

Build in a new output directory with `database.sqlite3`, `manifest.json`, and
`validation.json`. Use a sibling scratch SQLite database for streamed unique
keys. Bound memory and disk with explicit resource budgets, but fail rather
than truncate. Stream logical hashes in primary-key order. Check integrity,
foreign keys, exact table names, row accounting, dense dates, shape references,
and daily counts. Check source identity/hash again before publication. Fsync
and atomically rename a completed directory on the same filesystem; refuse an
existing output path. Remove only this invocation's scratch artifacts on
failure. The release ID is content-based and independent of file order/name.

#### Local country and continent catalog

Prepare Natural Earth Admin-0 Countries 1:10m, version 5.1.1, using the
source's de-facto country units. The source states that vector data are public
domain and distinguishes countries from sovereign states/map units. [Natural Earth Admin-0 Countries](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/) · [Terms of Use](https://www.naturalearthdata.com/about/terms-of-use/)

Keep the catalog outside the hotspot database and record its source URL,
archive SHA-256, version, attribution, and boundary policy. This build exposes
only the areas in scope: `country:VNM` and `continent:south-america`, made
from its 15 saved country members. Resolve `VN`, `VNM`, `Vietnam`, `Viet Nam`,
and `Việt Nam` to Viet Nam; resolve `South America` to the continent union.
Normalize Unicode NFC, case-fold, trim, and collapse whitespace. Other names
return 404; ambiguous names return 409 with candidate IDs.

The catalog builder reads Natural Earth country units and source continent
assignments, but it writes only these focused features and aliases. It
preserves holes and islands and rejects invalid included polygons rather than
repairing or dropping them.

Write `world-areas.geojson`, `area-aliases.json`,
`continent-membership.json`, and `world-areas-manifest.json` as UTF-8
canonical JSON. Compute `catalog_sha256` from domain
`apex4space.world-areas.catalog.v1\0`, the source archive SHA-256 text, and
each generated asset's sorted filename, 8-byte length, and bytes.
`catalog_version` is `ne-admin0-10m-5.1.1-` plus the first 16 hex digits of
that catalog hash. This makes the version change when source or catalog
contents change. Validate every hash, unit, alias, membership, geometry, and
bound when loading the catalog.

Named-area inclusion is `polygon.covers(cell_center)`. This reports active
cells whose center falls in the selected polygon; the original FIRMS point
may have been on the other side of a boundary within that cell. Return full
cell geometry and the separate area identity. Do not clip cell geometry to
the polygon or derive totals from displayed features.

#### Schema-2 API

Add versioned read-only endpoints; keep `/v1/hotspots/cells/query` and its
schema-1 response unchanged.

- `POST /v2/hotspots/query` accepts `release_id`, `area_name`, ISO `date`,
  `page_size` (default 1,000; maximum 10,000), and optional signed cursor.
  Resolve the name in the backend. Return `release_id`, `area_id`,
  `area_name`, `catalog_version`, `date`, sorted `grid_versions`, full
  `active_cell_count` before paging, `status`, `warnings`, a GeoJSON
  `FeatureCollection`, `returned_count`, `has_more`, and `next_cursor`.
  Each feature has stable `id`, `properties.grid_version`,
  `properties.cell_id`, and WGS84 geometry.
- Sort pages by `(grid_version, cell_id)`. Bind cursor to release hash,
  resolved area/catalog version, date, page size, grid version, and last key.
  Reject a cursor if any bound query value changes. A continent above 10,000
  matches succeeds over multiple pages.
- `POST /v2/hotspots/summaries/query` accepts `release_id`, `area_name`,
  `start_date`, and exclusive `end_date`; allow at most 366 days. Return a
  `release_id`, canonical area identity, catalog version, requested half-open
  date range, and one `days` entry per requested date. Each entry has ISO
  `date`, derived `active_cell_count`, `coverage_unknown`, and `input_state`.
  Include empty/unknown days. Clients page date windows to load longer histories.
- Select spatial candidates by indexed bounds, confirm exact point-in-polygon
  coverage once per cell, then join the selected IDs to date memberships. Use
  parameterized SQL and read-only connections. Stream candidates instead of
  loading all global shapes. Count before feature paging.
- Reject unsupported schema/grid, out-of-range dates, unknown/ambiguous
  names, invalid page parameters, changed cursors, and database timeouts with
  explicit errors: 404 `AREA_NOT_FOUND`, 409 `AREA_AMBIGUOUS` with candidate
  IDs or `UNSUPPORTED_SCHEMA`, 422 `DATE_UNAVAILABLE` with imported bounds or
  `INVALID_QUERY`, and 503 `DATABASE_UNAVAILABLE`/`QUERY_TIMEOUT`. Retain the
  five-second request deadline and measure country and continent queries on
  the completed database. A full database hash is checked during preparation,
  not on every map request.

GeoJSON remains longitude/latitude (EPSG:4326). The Leaflet client configures
its map CRS separately. For an EPSG:6933 view, use compatible Leaflet,
Proj4Leaflet, and Proj4js versions, explicit projected bounds/origin/zoom
resolutions, and a local world vector layer in the lowest pane. Ordinary Web
Mercator tiles do not belong in that view. Put country outlines and hotspot
cells in higher panes. Polar features remain in the database/API, with an
explicit EPSG:6933 display warning.

#### Compatibility, configuration, and rollout

Add optional `storage.global_release_path` and `storage.world_areas_path` to
`Settings` and `config/settings.json`. The first names one immutable schema-2
release directory containing `database.sqlite3` and its manifest; the second
names the four local catalog assets. Keep both separate from the pilot paths
in `config/processed-settings.json` and the legacy point database. If either
path is absent or invalid, return `503` from v2 and preserve v1 availability.
`scripts/check_results.py` dispatches by explicit schema version; the schema-1
checker remains unchanged. A schema-2 API request against a schema-1 release
returns an explicit unsupported-schema error. Build and verify before changing
the selected global release path. Keep the pilot path as rollback. Do not
convert either old database in place.

## 11. Phase 2 — Serve the data and connect the web app

### 11.1 Small technical design

Use Python, FastAPI, its request/response models, and SQLite through Python's
built-in `sqlite3` module. Use plain SQL in `storage.py` for legacy releases
and `processed_storage.py` for the processed-cell database.
Use CSV or compressed CSV for small interchange files and JSON for settings
and release records. Scientific code may use NumPy or another library only
where it is needed. Pin dependency versions after testing.

One offline script prepares the data. One app serves a selected, checked
release. Stop local serving during a release change in the MVP, or use a
checked transaction; never expose half-loaded tables. Run manual updates
first. Add a simple OS schedule only after the process is reliable.

No database server, Redis, Celery, message broker, or background export
service is needed for this local MVP. Add indexes only when measured queries
need them. Long calculations happen before serving.

Proposed folder layout:

```text
time-series-api/
  README.md
  pyproject.toml
  app/
    __init__.py
    main.py
    models.py
    sources.py
    harmonization.py
    analysis.py
    storage.py
    processed_storage.py
    local.py
    exports.py
  scripts/
    fetch_data.py
    prepare_data.py
    check_results.py
  config/
    settings.json
  tests/
  data/                 # local data; excluded from git
```

Create a new module when a file has a clear second responsibility, not just
to match a framework. The processed database and bounded export formatter
have separate responsibilities. Aim for code files below 500 lines and functions below
50 lines; split them when this improves understanding, not through empty
wrapper functions. Keep secrets and large data out of git.

`sources.py` owns download and source-reading functions; `harmonization.py`
owns offline matching, correction, and method checks. Scripts call those
functions. `analysis.py` calculates query results from saved typed data;
`main.py` never starts downloads or training. README links to this canonical
spec rather than keeping a second `development-spec.md`.

See [typed interfaces](time-series-api-signatures.md) for file-level class
fields, current processed-cell function signatures, security rules, and the
web handoff. Historical legacy signatures remain design context.

Freeze the source records used and selection rules with every release. Publishing
new standard data must not change an earlier release's points, totals, or
page cursors. Test an old query again after a new release is loaded. Record
file hashes and any fitted parameters; if a model is selected, verify
that saving and loading it preserves results before publication.

### 11.2 Leave a clear path to TimescaleDB

TimescaleDB works with PostgreSQL and adds tools for time-based tables [R10].
It is a future option, not an MVP dependency.

Keep legacy database calls in `storage.py` and processed-cell calls in
`processed_storage.py`; calculations and API handlers receive ordinary typed
data, not SQLite connections or SQL rows. Start with a few
named functions for observations, daily results, and releases. Avoid a
universal repository framework or unused adapter classes.

Use explicit IDs, UTC timestamps, named units, and parameterized SQL. Record
timestamp precision and conversion at the storage boundary. Avoid storing
Python objects in database blobs or relying on SQLite-only behavior in the
calculation code. A SQLite ID key may need redesign for a future TimescaleDB
time-partitioned table; do not promise a zero-change migration.

Move only when measured data size, concurrent access, or query time justifies
running a database server. Then replace the storage functions, add a small
PostgreSQL migration/import script, and run the same API and calculation
tests on the same sample data. Check row counts, units, timestamps, and
query results. Keep the SQLite copy until the comparison passes.

Add hypertables or database-built summaries only where useful after the move.
Keep the public API unchanged if its meaning is unchanged. Check feature
availability and license terms for the chosen TimescaleDB setup at that time.

### 11.3 Request rules

- Require a `release_id` so one screen and its downloads use the same data.
- For original data, require explicit `platforms` and keep that choice in
  point queries and exports. Each release lists allowed platforms.
- For harmonized results, use the release's fixed source rule. Reject source
  overrides with `REFERENCE_POLICY_CONFLICT`.
- Use WGS84 longitude/latitude: `west,south,east,north`.
- Include `start_date`; exclude `end_date`. Both use UTC.
- Reject rectangles crossing the 180-degree longitude boundary in the MVP.
- Reject an area/date query partly or fully outside the prepared release
  with HTTP 422 and `OUTSIDE_RELEASE_DOMAIN`; never silently trim it.
- If a release lacks the requested metric, return HTTP 409 and
  `METRIC_NOT_AVAILABLE`. In-range periods with no tested estimate return
  null with `not_validated` rather than a fabricated value.
- Default point pages to 1,000 rows; allow up to 10,000 rows per page.
- Allow only configured study areas and prepared dates. The requested
  historical range must also fit the local data and query-size limits.

#### Initial engineering limits

These limits are starting choices. Measure them during the pilot. They do not
validate a scientific method.

| Setting | Initial value |
| --- | --- |
| Candidate area | `[106, 10, 107, 11]` in longitude, latitude order |
| Candidate dates | 2026-09-01 inclusive to 2026-09-03 exclusive |
| CSV batch | 1,000 rows |
| Provider timeout and retries | 30 seconds and 2 retries |
| Request body and global rate | 16,384 bytes; 60 requests per minute in one process |
| Query | 3,660 days, 10 baseline years, 100,000 input rows, 10,000 cells, 5 seconds |
| Export | 10,000 rows, 8,388,608 bytes, 5 seconds |
| Old data | More than 3 UTC days since the latest source date |
| Rectangle edges | Include points on all four edges |
| Platforms per request | 1 to 16 unique names, each at most 64 characters |

The area and dates are candidates until the provider is checked. The MVP
accepts a rectangle only. A later polygon request needs a separate contract.
An empty source list and an unset release allow offline setup. No scientific
method may be selected until its inputs and tests are checked.

### 11.4 Endpoints

| Endpoint | Result |
| --- | --- |
| `GET /health/live` | Whether the app process is running. |
| `GET /health/ready` | Whether its database and selected release can be read. |
| `GET /v1/releases` | Releases, supported areas/dates, latest data dates, and available metrics. |
| `GET /v1/releases/{release_id}` | Sources, method/settings versions, and test report links. |
| `GET /v1/metrics` | Metric names, units, definitions, and allowed summaries. |
| `POST /v1/analysis` | Summary, calendar, coverage, historical comparison, quality labels, and area used. |
| `POST /v1/hotspots/query` | Pages of original observed points in GeoJSON. |
| `POST /v1/hotspots/cells/query` | Processed cell polygons and daily count from checked summary IDs and saved shapes. |
| `POST /v1/exports` | A bounded CSV or analysis-JSON download for the same query and release. |

The POST analysis and point endpoints only read data. For the MVP, exports
stream directly within a configured row/byte/time limit. Reject oversized
exports with HTTP 413 and ask the client to narrow the dates or area.
Do not add job IDs, a job-status endpoint, or a worker queue until real
export sizes show that direct downloads are not enough.

The point query and raw export use `release_id`, `bbox`, `start_date`,
`end_date`, and `platforms`. Point queries also accept `page_size` and an
opaque `cursor`. Exports add `kind` (`observations` or `analysis`) and
`format` (`csv` for observations, `json` for analysis). Analysis exports use
the analysis request fields below. Define the exact models in OpenAPI.

### 11.5 Analysis request example

This is an example only, not a prepared region or real release.

```json
{
  "release_id": "pilot-example-v1",
  "bbox": [106.0, 10.0, 107.0, 11.0],
  "start_date": "2026-11-01",
  "end_date": "2026-11-14",
  "metric": "harmonized_hotspot_count",
  "aggregation": "month",
  "comparison": {
    "mode": "same_elapsed_days",
    "baseline_start_year": 2020,
    "baseline_end_year": 2025
  }
}
```

Return the query, requested and used areas, release/method IDs, reference
count definition, unit, latest source date, response time, and warnings.
Return a summary, calendar periods, baseline, and coverage.

Each period includes start/end dates, `value`, `partial_value`, original
count under a stated source rule, expected/usable days, coverage numerator
and denominator, baseline median/years, differences, error information,
and `status`. Use null plus a reason for unknown values.

Statuses: `available`, `observed_zero`, `partial`, `low_coverage`, `missing`,
`insufficient_baseline`, and `not_validated`. Also return separate flags for
a partial calendar period and old data. These flags can overlap with status.
Set a documented threshold before labeling data old; use actual source dates.

### 11.6 Errors, files, and speed

Errors include `code`, `message`, `details`, and `request_id`.
Use 422 for invalid inputs, 404 for unknown releases, 409 for missing metrics,
413 for oversized queries/downloads, 429 for request limits, and 503 for a
temporary server problem. A missing historical baseline is a null field with
a reason in a valid response, not a server error.

Keep original point exports separate from estimated totals. Never invent
point coordinates from a count estimate. Keep source, band names, method,
release, units, and coverage clear. GeoJSON coordinates use longitude first.
Escape untrusted text that could act as a spreadsheet formula in CSV files.

Sort point pages by observation time and ID. Bind the cursor to the query
and release. Results must stay the same while the client reads more pages.
Screen values and downloaded analysis must match exactly.

Proposed local target: 95% of typical pilot analysis requests and first point
pages finish within two seconds on declared hardware. Measure before adding
caches or services. Add a small in-process cache only if needed, keyed by
query and release. Do not train models inside an API request.

Keep credentials server-side, allow only configured web origins, and limit
request size and rate. Logs record errors and timing without keys. Public
read access and later authentication remain deployment choices.

### 11.7 Web developer handoff

Provide OpenAPI, the metric definitions, small real examples, clearly marked
invented test cases, request examples, download examples, source credits,
and supported areas/dates. The frontend should show simple results first
and expose source/method details when the user opens them.

Test the full path: move map, draw area, select dates, view calendar, open a
month, inspect points, compare with history, and download matching results.
Missing periods must remain visible. An unsupported area must not look like
an area with no fire activity.

**OpenLayers contract [R14]:** use its rectangle drawing interaction, then
convert the selection from the map view projection to `EPSG:4326` before
sending `west,south,east,north`. A Web Mercator view may use `EPSG:3857`;
those coordinates are not API longitude/latitude. Use an unrotated view for
the MVP's north/south/east/west rectangle. Reject selections crossing 180° longitude;
world wrapping must not turn them into a different valid rectangle.

Read GeoJSON with explicit `dataProjection: 'EPSG:4326'` and the actual view
`featureProjection`. The processed cell route accepts one date and exactly
one prepared `area_id` or containing `bbox`; it returns one polygon per cell,
the filtered count, status, and warnings. Draw the cell layer above the
basemap. Keep `coverage_unknown`, `partial`, `missing`, `observed_zero`, and
available states visible and distinct. Send a request at draw completion or
Apply. Cancel or ignore older requests, and replace the previous layer when
the query changes. The legacy point route remains separately paginated;
loaded point pages must not appear as the area's total.

The local pilot's visible OpenLayers placement, count, and missing/partial
state rendering have not yet received web developer approval. Verify polygon
placement, the count, and those status states together before calling the
web handoff complete.

Test coordinate conversion in both study areas, including negative longitude
and latitude. Test date selection without browser-local timezone shifts,
release pinning across calendar/points/downloads, and visible requested versus
used cell areas. Choose a basemap provider separately and follow its use and
attribution terms; OpenLayers itself does not supply a production tile service.

### 11.8 Demo and deployment handoff

Keep the checked local MVP and a public challenge demo as separate milestones.
The Notion notes propose cloud hosting but choose no provider [R11]. After
local checks, use one small API deployment with persistent storage and the
same fixed release; manual publication is enough. Do not introduce cloud
stream processing. Keep a local copy and a recorded demo if hosting fails.

Before sharing, test the deployed frontend/API together, HTTPS, allowed
origins, database persistence, and limits. Serve validation reports through
explicit public links, never by exposing the whole data folder. A public
demo must state whether it shows original, research, or validated harmonized
results. Failed science checks do not become passed checks for a deadline.

The supplied organizer slides request a public project/demo link, source and
tool credits, and disclosure of AI-tool use [R12]. They show a maximum of seven
slides or a 30-second video; verify current submission instructions before
submitting. Demonstrate one real saved query and its matching download. Keep
invented edge cases clearly marked. Name one delivery owner and one reviewer
for the data release and frontend handoff; the Notion role entries do not yet
assign people. These are handoff tasks, not new API services.

## 12. Checks before calling the MVP complete

| Check | Required result |
| --- | --- |
| Data | Required source and coverage data exist, fit the budget, and pass checks. |
| Science | FRP test completed; count method separately tested on unused data. |
| Scope | Every claimed area, year, satellite, and product has test support. |
| History | Published comparisons have at least five usable earlier years. |
| API | Request rules, null values, errors, paging, release versions, and downloads work. |
| Users | The emergency responder, scientist, land manager, and web developer stories pass. |
| Simplicity | One local app works; extra layers have a written, measured reason. |

Tests must cover time parsing, repeated records, zero FRP, measurement-limit
flags, area edges, missing versus zero, equal historical windows, zero
baselines, repeatable random outputs, source changes, and unsupported areas.
Scientific tests use independent data, not just copies of the code's formula.

Also test mixed archive/NRT schemas, type/unknown handling, textual product
versions, retention of unmatched observations, bounded import memory, release
repeatability after source replacement, and the OpenLayers handoff above.

Do not call the method validated because two totals match. Do not call a
short sample a historical baseline. Do not call the API a complete web app.

## 13. Work order and open choices

1. **Phase 1:** choose small rectangles; check availability, file sizes,
   source coverage, and key use.
2. **Phase 1:** run the small Aqua–Suomi FRP test; keep or change the method.
3. **Phase 1:** test a common count, then prepare a checked historical release.
4. **Phase 2:** build the small local API and its documentation.
5. **Phase 2:** connect the web app and test the full user path.
6. **Later:** expand toward 2000–2026 and wider areas; move to TimescaleDB
   only if measured needs justify it; revisit brightness prediction if useful.

Mock API examples may be written during Phase 1 so web work can proceed.
Do not serve experimental estimates as checked scientific results.

Open choices: exact areas, measured data size, usable historical years,
count method, reference visit schedule, final test thresholds, hosting,
update rate, and data-age labels. These must be recorded before the related
feature is published; they need not all be settled before the small test.

Start with manual local updates. Later, a simple daily scheduled command may
fetch available new data, check it, and write a new release. A release records
actual data dates; it does not promise real-time updates. Handle standard-data
replacements through new releases.

This spec describes proposed work. It does not claim that the count method,
MVP data volume, API, or TimescaleDB migration has already been tested.

## 14. Sources

- **R1.** NASA Space Apps Challenge: [Harmonization of MODIS and VIIRS Hot Spots](https://www.spaceappschallenge.org/2026/challenges/modis-and-viirs-hot-spots/). Also read the supplied PDF, pp. 4–5.
- **R2.** Sofiev and Kouznetsov (2026): [Observation operator and detection limits for MODIS and VIIRS Fire Radiative Power products](https://doi.org/10.5194/gmd-19-10123-2026). Published 26 October 2026. See Sections 3.3–3.5.
- **R3.** FMI: [FRP_OOp](https://github.com/fmidev/FRP_OOp). Reviewed pixel file blob SHA: `e91119e87a52d9e33e05fc9bef93b4f8f403eab1`; README blob SHA: `2b72cb13659f0963315278679c5327417494fe92`. Save a full repository commit before implementation and check dependencies and license terms.
- **R4.** Schroeder, Giglio, and Hall (May 2024): [VIIRS Collection 2, 375 m Active Fire User's Guide](https://ladsweb.modaps.eosdis.nasa.gov/archive/Document%20Archive/Science%20Data%20Product%20Documentation/VIIRS_C2_AF-375m_User_Guide_1.0.pdf), Sections 3.1.2–3.1.3.
- **R5.** NASA LAADS: [VNP02MOD](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP02MOD/).
- **R6.** NASA FIRMS: [MODIS fields](https://firms.modaps.eosdis.nasa.gov/content/descriptions/FIRMS_MODIS_Firehotspots.html) and [VIIRS fields](https://firms.modaps.eosdis.nasa.gov/content/descriptions/FIRMS_VIIRS_Firehotspots.html).
- **R7.** NASA FIRMS: [Python API tutorial](https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html). Reviewed 2026-11-13; example dates are not live availability.
- **R8.** NASA FIRMS: [Area API](https://firms.modaps.eosdis.nasa.gov/api/area). Reviewed 2026-11-13 for area order, dates, day limits, and transaction limits.
- **R9.** NASA FIRMS: [Data availability API](https://firms.modaps.eosdis.nasa.gov/api/data_availability).
- **R10.** Tiger Data: [TimescaleDB](https://www.tigerdata.com/timescaledb). Reviewed 2026-11-13. Use official setup documentation when migration becomes necessary.
- **R11.** Team Notion: [apex4space](https://www.notion.so/40f07acf01e080ea93dbd6a6b3c07551). Reviewed 2026-11-13, including its child pages and database entries. Source of team proposals, not scientific validation.
- **R12.** Team Notion: [pre-event meet-up](https://www.notion.so/41307acf01e080f8bf46cf712e6e3935). Reviewed its 13 attached organizer screenshots on 2026-11-13. Submission guidance is supplied material, not a fresh confirmation from the organizer.
- **R13.** Linked Drive: [Data folder](https://drive.google.com/drive/folders/1_RbaB1o7lrmOlzsp8CGq34Oe_rQ_lKMc) and [modis-viirs-eda.ipynb](https://drive.google.com/file/d/1eMPsOpfFKwNtyGgNLqAp7CH92G67V5Qz/view). Folder metadata, four README files, notebook code, and saved text outputs reviewed 2026-11-13; full CSV/ZIP contents not reread. See the [review log](../logs/2026-11-13/research/notion-spec-review.md) for coverage and limits.
- **R14.** OpenLayers official documentation: [box drawing](https://openlayers.org/en/latest/examples/draw-shapes.html), [coordinate transforms](https://openlayers.org/en/latest/apidoc/module-ol_proj.html), and [GeoJSON projections](https://openlayers.org/en/latest/apidoc/module-ol_format_GeoJSON-GeoJSON.html). Reviewed 2026-11-13. Pin the web app's tested version during implementation.
- **R15.** NASA FIRMS: [download README](https://firms.modaps.eosdis.nasa.gov/download/Readme.txt). Reviewed 2026-11-13 for source provenance, NRT replacement, geographic coordinates, credits, and use limitations. Its platform-availability notes differ from the linked notebook; verify the actual products before use.
- **R16.** Li et al. (2018): [Comparing MODIS and VIIRS active fire products for their sensitivities to fire size, fire duration, and fire radiative power](https://doi.org/10.1029/2017JD027823). FRP differences depend on scale and observation conditions; do not reuse one published factor as a universal correction.

Confidence is high for the source-field definitions and the distinction
between FRP and counts. Confidence in the proposed count method and its
accuracy remains open until the tests are complete.

## 15. Revision decisions and terminology

Compared v0.4 with v0.3, `documents/specs/brainstorming.md`, the proposed
directory design, and the Notion materials [R11–R13]. Earlier v0.1/v0.2
texts were not found in the available local specs. No existing runtime
object, table, metric, endpoint, or checkpoint field is renamed.

| Earlier name | v0.4 name | Status | Owner and evidence |
| --- | --- | --- | --- |
| `source_file`, `observation`, `band_measurement`, `opportunity`, `analysis_daily`, `release` | Same names | unchanged | Storage; v0.3 §10.1 and §11.2. Source records used are fixed by §11.1. |
| Five metric names in §10.2 | Same names | unchanged | Analysis; v0.3 §10.2. Type policy is explicit, not a wildfire/event-count rename. |
| Request/response fields and status names | Same names | unchanged | API; v0.3 §11.3–11.6. OpenLayers converts coordinates before the same request. |
| `REGION`, `UNIFIED`, `FIRE_ID`, `ECONOMIC_IMPACT` in Notion | No MVP equivalent | deprecated for this MVP proposal | Deferred event/impact research. These are not aliases for cells, observations, or count estimates. |
| No chosen map library | OpenLayers | new decision | Frontend; team's explicit instruction on 2026-11-13, implemented through §11.7. |
| CLI ingestion / source streams | Bounded offline ingestion | unchanged ingestion purpose | Preparation; earlier brainstorming and §8. No continuous-stream runtime is introduced. |

The selected path is a saved small API sample, then tested harmonization,
then a calendar/API release and OpenLayers integration. Full archive imports
increase storage needs; live streaming adds failure and deployment work.
Neither is required for the first MVP. Exact scientific choices remain open
until the tests in §9 resolve them. The directory proposal remains a design,
not evidence of implementation or successful runtime checks.

### v0.5 changes

Compared v0.5 with the available v0.4 text and its v0.3 mapping. The full
v0.3 file is not present in this repository, so this revision makes no new
claims about v0.3 object identity.

| v0.4 object or choice | v0.5 name or choice | Status | Owner and change |
| --- | --- | --- | --- |
| `source_file`, `observation`, `band_measurement`, `opportunity`, `analysis_daily`, `release` | Same names | unchanged | Storage objects remain the same. Daily FRP storage needs review before implementation. |
| `frp_pass_sum_mw` | Same name and pass-only meaning | unchanged | Analysis metric remains one pass; do not sum across passes. |
| 1 km equal-area grid proposal | Cell side length `w` km | clarified | Grid design; projection, origin, ID, and edge rule must be frozen in T9. |
| No daily cell FRP definition | Per-platform daily peak of per-pass cell sums | new scientific definition | T10 experiment; not yet an API metric and not evidence of sensor comparability. |
| No FRP correction choice | Raw paired comparison, then one fitted scale factor | new experiment order | T10; keep the factor only if it improves held-out data. |
| Existing map API contract | Same current contract | unchanged for now | New cell-map response needs a web review and OpenAPI update in T13. |

No Python class, table, endpoint, request field, response field, or checkpoint
name changes in v0.5. Do not implement the planned daily FRP as an unreviewed
extension of `DailyRecord` or the current map response.

### Earlier schema draft — 2026-11-14 (superseded by §10.6)

Compared with the six-table v0.5 design, the current storage schema, and the
schema discussion note. These are proposed additions, not applied migrations.

| Existing name | Draft name | Status | Owner and boundary |
| --- | --- | --- | --- |
| Six tables in §10.1 | Same names | unchanged | Storage; preserve their existing meanings and data. |
| No saved cell geometry table | `hotspot_cell` | new | Storage; sparse full-cell geometry by grid version. |
| No release-specific cell link | `cell_detection` | new | Preparation/storage; source observations stay grid-independent. |
| No per-platform cell/day table | `hotspot_cell_day` | new | Preparation/storage; does not rename `analysis_daily` or `DailyRecord`. |
| Hotspot meaning a source point | Source detection; hotspot cell | split terminology | Shared glossary; existing point-route field names remain unchanged. |
| No named-area request field | `area_id` | new, planned | API; one catalog for nations and other named areas. |
| Point query route | Same route plus a separate cell route | unchanged plus planned addition | API; preserve the point contract and review the new cell contract separately. |

No source, model, config, checkpoint, or OpenAPI field has migrated in this
documentation step. A later implementation plan must name the affected files.

### Earlier daily count clarification — 2026-11-14 (storage superseded by §10.6)

- `active_cell_count`: same distinct-cell meaning; now required for planned
  daily cell analysis. Owner: analysis. No existing API metric is renamed.
- `daily_hotspot_summary`: new derived query result, not a stored table/view.
  Owner: analysis/API; counts distinct cells across selected platforms.
- `hotspot`: short name for hotspot cell in the cell design. Source detections
  and existing `observed_hotspot_count` retain their separate meanings.
- No database migration, source-code change, or OpenAPI update is applied here.

### Simplified count-first schema proposal — 2026-11-14

| Earlier object | Proposed object | Status | Owner and boundary |
| --- | --- | --- | --- |
| `source_file`, `observation`, `release` | Same names | unchanged | Storage; core source identity and release records. |
| `hotspot_cell`, `cell_detection` | Same names | unchanged proposals | Preparation/storage; sparse shapes and release-specific assignments. |
| Derived-only `daily_hotspot_summary` | Stored `daily_hotspot_summary` | changed lifecycle | Preparation writes area/day counts; API reads them. Same count meaning, now persisted by user request. |
| Proposed `hotspot_cell_day` | No core equivalent | deprecated proposal for count-first MVP | Group linked observations for map counts. FRP storage remains open; no runtime table is removed. |
| `analysis_daily`, `band_measurement`, `opportunity` | Same names | unchanged | Existing science support; no area/day alias or data deletion. |
| `active_cell_count` | Same name | unchanged | Distinct cells per UTC day; union across release-selected platforms. |

This proposal changes the previous platform-row storage choice. No source,
config, model, checkpoint, SQL table, or OpenAPI migration is applied. Planning
must cover preprocessing, storage/models, API/exports, examples, and validation
before implementation. Earlier revision text above is retained as history.

### Responder display scope — 2026-11-14

The user limited the responder MVP to cell shapes and daily hotspot counts.
The proposed `daily_hotspot_summary.hotspot_cell_ids` is a new stored field,
owned by preprocessing/storage. Raw source records and cell links stay unchanged.
Responder reads use summary IDs and `hotspot_cell` geometry instead of raw
record joins. No database or OpenAPI migration is applied in this draft.

### Drive CSV input refinement — 2026-11-14

Proposed new `app/drive.py` owns Drive metadata and bounded byte extraction.
Existing source normalization is reused through a proposed `read_source_rows`
entry point. Database/table meanings and responder output remain unchanged.
The implementation plan now uses Drive CSVs as its primary preprocessing input;
no code or credentials have been added in this documentation change.

### Three-table local MVP — 2026-11-14

The user's three-table instruction supersedes earlier table proposals above.

| Earlier object | New design | Status | Owner / migration |
| --- | --- | --- | --- |
| `observation` rows plus `cell_detection` links | Detection and assignment in `cell_detection` | merged | Preparation/storage; preserve raw IDs/fields in payload and validate grid links. Earlier link-only schema is not equivalent. |
| `hotspot_cell`, `daily_hotspot_summary` | Same tables | unchanged | Cell shapes and stored area/day counts/IDs. |
| `source_file`, `release` metadata tables | Release manifest and validation files | moved persistence | Preparation/storage; no table copies; check local metadata at startup. |
| Science support tables | No new-MVP table equivalent | deferred | Existing data are not deleted; new unsupported science requests fail clearly. |

No database or source code was changed by this documentation update.

### Processed-only storage — 2026-11-14

The user's processed-only instruction supersedes earlier local raw retention.

| Earlier object | Current MVP | Status | Owner and migration boundary |
| --- | --- | --- | --- |
| `cell_detection` and `CellDetectionRecord` | No persisted equivalent | deprecated for this MVP | Preprocessing uses raw rows transiently; no local raw table or link file. |
| `hotspot_cell`, `daily_hotspot_summary` | Same names and meanings | unchanged | The only two user tables in the new dataset. |
| Per-row source selection | File/version/hash + declared filters and counts | changed provenance form | Release metadata; no retained row-ID arrays. |
| Raw point/detail reads | Legacy releases only | narrowed scope | New processed releases return explicit unsupported errors. |

No source, database, configuration, or OpenAPI migration is applied here.

### All-date FIRMS database and named-area API — 2026-11-14

This is the newest contract and supersedes the schema-1 pilot's two-table,
one-grid, area allowlist, size caps, and OpenLayers handoff only for schema-2
releases. The pilot and v1 routes remain unchanged.

| Earlier object or choice | Schema-2 object or choice | Status | Owner and migration |
| --- | --- | --- | --- |
| `hotspot_cell` | Same table concept with row/column, projected bounds, WGS84 center, and geometry | clarified | New importer; `grid_version` changes identity, never reinterpret EPSG:8857 cells. |
| `daily_hotspot_summary` keyed by `(release_id, area_id, date)` with JSON cell IDs | Global/day summary keyed by `(release_id, date)` plus area-derived API summary | split | Importer owns `area_id='world'`; backend computes named-area counts. |
| Summary JSON `hotspot_cell_ids` | `hotspot_cell_day` | new | Importer writes compact membership keys with SQL foreign keys to shape/day. |
| `pilot-10km-v1`, EPSG:8857 | Three 10 km grids in EPSG:6933/6931/6932 | new | Global importer; latitude −86°..+86° inclusive is 6933, outside bands use the matching polar grid. |
| Exact local `source_files` allowlist, date/platform/area filters | Recursive filename-agnostic CSV discovery with all rows/dates/sensors | replaced in new path | Portable script; schema-1 preparation remains intact. |
| Pilot rectangle `AreaRecord` | Natural Earth local country/continent polygon catalog | new | `app/areas.py`; no runtime geocoder. |
| `/v1/hotspots/cells/query` | `/v2/hotspots/query` and `/v2/hotspots/summaries/query` | new version | v1 payload stays stable; v2 checks schema 2 and pages large results. |
| OpenLayers view | Leaflet custom EPSG:6933 map view | changed by user | New global frontend contract only. GeoJSON remains EPSG:4326; polar bands need a separate display contract. |

The standalone importer reads every valid row or fails the build. Multiple
sensors/pass detections in one cell on one UTC day become one membership;
distinct cells are retained. All calendar dates between observed bounds are
stored, with `coverage_unknown` even on zero-count days. This is an active-cell
count, not an independent fire-event count or observation-coverage estimate.
No source row, FRP, or brightness value is stored. The new API reads only the
checked database and local polygon catalog. The user's request to execute
`plan-firms-all-dates.md` authorizes the phase order and the supplemental polar
grids needed to preserve all valid rows; it does not authorize visual approval
or external developer contact.

### Local OpenLayers web MVP — 2026-11-14

The user's latest request selects OpenLayers for the schema-2 MVP, replacing
Leaflet. `web-app/` is a static page served by `app.web.create_web_app` beside
the existing v2 API. It uses the same release, dates, exact center rule, full
counts, and signed paging. The whole interface fits the window. Map notes
open in a dialog. Daily bars show the selected month and select its date.
The plain Natural Earth world background and simplified area outlines are
for display; the backend still filters with the exact catalog geometry.
The map is EPSG:6933 and GeoJSON remains EPSG:4326. Run instructions are in
`web-app/README.md`.

Terminology: `OpenLayers map` replaces `Leaflet map` in the current frontend
contract. Database tables and API object names are unchanged.
