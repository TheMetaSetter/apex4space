# Daily FRP and shared cells

Date: 2026-11-14

- This note checks the spec, runtime, OpenAPI, and primary sources. After the
  user clarified `w` and the daily value, the spec and checklist were updated.

## Matches

- The spec proposes a 1 km equal-area grid and says to record its size and
  version. It also says a grid alone does not make the sensors comparable.
- `DailyRecord` already has a cell ID, cell shape, cell center, day, source
  count, optional reference count, coverage, and status.
- The runtime assigns whole grid cells to a requested rectangle by testing
  each cell center. It separately selects raw observation points by their
  coordinates. This is not yet the proposed record-to-cell assignment.
- The raw observation record and point response keep each source FRP value in
  MW. No correction is applied to that raw value.
- `active_cell_count` exists as an optional metric. It counts cells with
  detections and is separate from detection count.
- The spec already requires matched MODIS–VIIRS passes, footprint checks,
  unmatched records, and tests of the FRP observation operator.

## Conflicts and missing decisions

- The spec's grid is a 1 km proposal. It does not define a global tunable
  `w × w` grid. A global grid needs a width unit, equal-area projection,
  origin, cell IDs, and a fixed edge rule. Degree squares do not have a fixed
  ground area around the world.
- The proposed cell rule says a record belongs to the cell that contains the
  record's center. The current runtime does not assign point records to cells.
- A cell's hotspot flag needs a time and source rule. No detection can mean
  either no detected hotspot or no usable observation. Coverage must keep
  these states separate.
- The spec defines `frp_pass_sum_mw` for one satellite pass. It says not to
  sum values across different times and call the result emitted energy. The
  API rejects day/month aggregation for this metric.
- There is no daily FRP metric. `DailyRecord` and `analysis_daily` store no
  FRP value. OpenAPI lists `frp_pass_sum_mw`, but does not offer a daily FRP
  result.
- The spec plans an FRP operator test. It does not compare a plain global
  ratio or linear adjustment as a separate simplest candidate.
- “Daily FRP” is not defined. A sum across all detections and passes may count
  repeat observations. FRP is power in MW at an observation time, not energy
  over a day.

## Small experiment path

- Keep each original per-record FRP value unchanged.
- Assign each observation center to one fixed equal-area cell. Keep the cell
  size `w` and grid version with the release.
- For each cell and pass, sum valid FRP separately for MODIS and VIIRS. Compare
  paired, near-time passes on matching ground areas. Keep missing coverage
  separate from a valid zero.
- First measure the uncorrected difference. Then test one simple scale or
  linear correction on tuning data. Keep it only if it improves held-out
  dates or areas. Report errors by FRP range, day/night, scan angle, and area.
- Do not use one global factor as an assumed truth. A published comparison
  found that sensor differences change with spatial scale, ecosystem, fire
  size, and viewing angle.
- If the team needs one daily number, a possible simple definition is the
  highest valid area-wide pass sum during the UTC day. Call it a daily peak
  observed pass FRP, in MW. Do not sum different passes and call it daily
  emitted energy. This rule still needs team approval and validation.
- Keep a combined or corrected daily value unavailable until an independent
  test passes. A map can still show raw sensor-specific points and values.

## Team choices and current gap

- The user chose `w` as cell side width in km, not the number of grid rows or
  columns. T9 still needs to freeze the equal-area projection, origin, cell ID,
  edge rule, and a tested value of `w`.
- A cell is active for a UTC day if either sensor has a selected detection in
  it. Keep counts and presence by platform separate.
- The user chose the highest valid pass sum in one UTC day as the daily value.
  Since MODIS and VIIRS are not yet comparable, the spec defines one peak per
  cell and platform. It does not add different passes or combine platforms.
- Report zero only when usable coverage confirms a visit with no detection.
  Unknown coverage stays unknown. A hotspot alone does not show that a cell
  had a usable visit when it had no detections.
- The simple comparison order is: (1) compare uncorrected cell/pass sums on
  paired, near-time passes with matching usable area; (2) fit one scale factor
  on tuning data; (3) keep it only if it improves results on held-out dates and
  areas. This is an experiment, not an approved universal correction.
- This plan fits the spec's warning that a grid alone does not make sensor
  values comparable. The current API still exposes raw point FRP and a
  pass-only area sum. It has no daily cell FRP result.
- The web developer approved rectangle queries and point paging. A cell map
  needs a separate review of its geometry, values, and coverage states before
  the OpenAPI contract changes.

## T9 native-input check

- The shared Drive `Data` folder contains FIRMS CSV exports. The checked
  entries include `fire_nrt_M-C61_842795.csv` and
  `fire_archive_M-C61_842795.csv`, plus `fire_nrt_SV-C2_842798.csv` and
  `fire_archive_SV-C2_842798.csv`. The archive CSVs are large. Do not download
  them for this MVP.
- Searches for `MYD14`, `MYD35`, `VNP14IMG`, and `VNP03IMG` found no native
  product files. The folder data cannot verify native pass IDs, granules,
  masks, geolocation quality, or actual file sizes.
- **MYD14:** NASA lists Aqua MYD14 as a Collection 6.1, 5-minute, 1 km Level-2
  fire swath. The C6/C6.1 guide defines the fire mask and algorithm QA as bit
  fields, fire-pixel latitude/longitude in degrees, and fire-pixel power in
  MW.
  The mask separates unprocessed, water, cloud, no-fire, unknown, and three
  fire-confidence classes. The product page lists a typical file size near
  0.4 MB. The listed `MYD14` file is a fire source; it does not supply a full
  coverage history by itself.
- **MYD35_L2:** NASA lists the Aqua cloud mask as a 5-minute, 250 m/1 km
  Collection 6.1 HDF-EOS product. It includes cloud mask and QA fields. The
  product reference gives about 15 MB as a maximum file size. It is a quality
  input, not a fire record source.
- **VNP14IMG:** NASA lists a Suomi-NPP VIIRS 375 m Level-2 product in Collection
  2.0. The file is NetCDF4/HDF5 and covers a six-minute orbit segment. Its
  filename contains platform, acquisition day/time, collection, and
  processing time. It has a fire mask, algorithm QA, fire-pixel locations,
  and `FP_power` in MW. The guide identifies non-processable, cloud, water,
  no-fire, fire, and bow-tie states; those flags must not be reduced to a
  single fire/no-fire bit.
- **VNP03IMG:** NASA lists a matching six-minute 375 m geolocation product in
  NetCDF4. It supplies WGS84 pixel-center latitude/longitude and geolocation
  quality fields. Its acquisition timestamp and collection must match the
  selected VNP14IMG granule. A file-name time match still needs a content and
  footprint check.
- These product docs establish expected formats and fields. They do not
  establish the exact versions, paired granule IDs, row values, usable masks,
  or file sizes for the team's missing data. The file-size figures above are
  product-page estimates, not measured pilot sizes.
- Minimum reader choices, based on those documented formats:
  - `pyhdf==0.11.7` (MIT) for the MODIS HDF4/HDF-EOS SDS fields.
  - `netCDF4==1.7.5.1.post1` (MIT) for the VIIRS NetCDF4/HDF5 files.
  - Do not add `h5py` or `xarray` for this reader. Do not add `pyproj` here;
    grid projection is a separate step. These libraries are selected but not
    installed. Install and test them only with the small checked files.
  - The current environment is Python 3.13.5 on macOS 26.6.2 arm64. PyHDF has
    a matching wheel; netCDF4 has a compatible macOS arm64 wheel. Check these
    versions again before install.
- NASA now reports that S-NPP product delivery stopped on 2026-11-01. The
  planned study dates are in September 2026, but later requests must check
  archive availability. For a science comparison, use the standard archived
  products where available; NRT is a less stable input.
- The documented formats support the reader choices above. The current Python
  environment has NumPy and Shapely, but no `pyhdf`, `netCDF4`, `h5py`,
  `h5netcdf`, `xarray`, or `pyproj`. Do not install the selected readers until
  the actual native files are available for a small import check.
- The reviewed notebook has NOAA-21 rows dated March 2023, while the checked
  FIRMS availability page starts NOAA-21 coverage on 2024-01-17. Its saved
  MODIS rows include versions `6.03` and `61.03`, with no checked collection
  mapping. No matching native pair is available. Exclude these rows from
  harmonization claims until product identity and dates are checked. The
  separate local VIIRS sample also has mixed `2.0NRT` and `2.0URT` versions;
  the source reader preserves those row versions.
- Official product references:
  - [NASA MYD14 product page](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MYD14)
  - [NASA MYD35 product format and content](https://atmosphere-imager.gsfc.nasa.gov/products/cloud-mask/format-content)
  - [NASA MYD35 collection 6.1 reference](https://atmosphere-imager.gsfc.nasa.gov/products/cloud-mask/doi-reference)
  - [MODIS C6/C6.1 active-fire user guide](https://modis-fire.umd.edu/files/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf)
  - [NASA MODIS cloud-mask page](https://atmosphere-imager.gsfc.nasa.gov/products/cloud-mask)
  - [NASA VIIRS active-fire product guide](https://viirsland.gsfc.nasa.gov/PDF/VIIRS_activefire_User_Guide.pdf)
  - [NASA VIIRS Collection 2.0 active-fire guide](https://ladsweb.modaps.eosdis.nasa.gov/archive/Document%20Archive/Science%20Data%20Product%20Documentation/VIIRS_C2_AF-375m_User_Guide_1.0.pdf)
  - [NASA VIIRS product details](https://viirsland.gsfc.nasa.gov/Products/NASA/FireESDR.html)
  - [NASA VNP14IMG file specification](https://ladsweb.modaps.eosdis.nasa.gov/filespec/VIIRS/1/VNP14IMG)
  - [NASA VNP03IMG product page](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP03IMG/)
  - [NASA VNP03IMG file specification](https://ladsweb.modaps.eosdis.nasa.gov/filespec/VIIRS/1/VNP03IMG)
  - [PyHDF package release and license](https://pypi.org/project/pyhdf/)
  - [netCDF4 package release and license](https://pypi.org/project/netCDF4/)
  - [NASA S-NPP product delivery notice](https://www.earthdata.nasa.gov/data/alerts-outages/suomi-npp-data-product-delivery-cease-november-1-2026)

T9 is now at item 5. The reader libraries are selected, but not installed.
The actual-file checks in item 2 are still open. The projection, grid origin,
cell IDs, edge rule, pass schedule, quality rules, held-out splits, and numeric
acceptance targets also remain open. Do not write a native reader or start T10
until a small matching native sample is available and its identity and dates
are checked.

## Sources

- Development spec v0.5: §§3.1, 7.2–7.4, 9 Step B, and 10.2.
- Runtime: `app/models.py`, `app/analysis.py`, `app/main.py`, and
  `openapi.json` in `time-series-api/`.
- [NASA VIIRS product guide](https://viirsland.gsfc.nasa.gov/Products/NASA/FireESDR.html):
  VIIRS product resolutions and the continuity role of the 750 m product.
- [NASA VIIRS 375 m active-fire algorithm guide](https://viirsland.gsfc.nasa.gov/PDF/VIIRS_activefire_375m_ATBD.pdf):
  FRP uses pixel area, radiance difference, and a sensor coefficient; pixel
  area varies with scan angle; I4 saturation affects retrieval.
- [Li et al. 2018, MODIS–VIIRS FRP comparison](https://doi.org/10.1029/2017JD027823):
  paired-sensor FRP differences vary with scale, ecosystem, fire size, and
  view angle. The reported 1-degree-grid difference is not a universal
  correction factor for smaller cells.
