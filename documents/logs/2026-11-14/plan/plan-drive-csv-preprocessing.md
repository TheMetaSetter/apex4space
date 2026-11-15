# Direct Drive CSV preprocessing plan

Date: 2026-11-14. Status: processed-only revision; no implementation or content scan ran.
Main checklist: [detailed plan](../detail/detail-responder-hotspot-mvp.md).
This replaces the retained-raw-row design and its three-table output.

## Input and observed inventory

Root: [Data South America](https://drive.google.com/drive/folders/1_RbaB1o7lrmOlzsp8CGq34Oe_rQ_lKMc).
The root and all four sensor subfolders were listed on this date. Only metadata
was read. The connector did not return checksum/version fields in the two
selected metadata responses; runtime verification must request them directly.

| Source family | Kind | CSV name | Drive file ID | Bytes |
| --- | --- | --- | --- | ---: |
| MODIS | NRT | `fire_nrt_M-C61_842795.csv` | `18LjhjUjJ8vRokZcbc1O-d3k9TKldn4vk` | 14,333,689 |
| Suomi-NPP | NRT | `fire_nrt_SV-C2_842798.csv` | `1RzdWep7rqAQ--WdQWH1cp5X_pqeBIVBa` | 64,702,393 |
| NOAA-20 | NRT | `fire_nrt_J1V-C2_842796.csv` | `1LPjsgAFGyJX4ksvKGxAgrcaAjNaU4Y8l` | 70,265,198 |
| NOAA-21 | NRT | `fire_nrt_J2V-C2_842797.csv` | `1NpfxhEUihk_wlylonpHaToIraKC0Z3OJ` | 67,723,546 |
| MODIS | archive | `fire_archive_M-C61_842795.csv` | `1ePdKQuxO7y79lI_F4EajOZ--mKTmvJxJ` | 1,408,411,858 |
| Suomi-NPP | archive | `fire_archive_SV-C2_842798.csv` | `1Jd1g-_rc_QDzY3lWb_P_ctrD79kfa944` | 2,947,153,227 |
| NOAA-20 | archive | `fire_archive_J1V-C2_842796.csv` | `1ebVMOphMtW1eAMnGPh3a5HUgAS0q-hI2` | 1,753,113,864 |
| NOAA-21 | archive | `fire_archive_J2V-C2_842797.csv` | `1-gwcfpvF_fNJpIdFircoU6UzHL45ooQr` | 681,199,204 |

Re-list before execution; do not assume these files never change. Recurse into
real child folders, visiting each folder ID once and following all list pages.
Allow only stored files with a case-insensitive `.csv` suffix and a CSV/text
MIME type. Skip `.zip`, `.ipynb`, Google notebooks, other files, and shortcuts
before any content request. Do not unpack archives or run notebooks.

## Processed-only path

Drive byte stream → checked transient CSV rows → unique UTC day/cell sets →
`hotspot_cell` + `daily_hotspot_summary` → local API.

Never write raw rows, full CSVs, or a detection-link file locally. Each row is
validated, assigned by center, and discarded. Merge sets across sensors and
passes; a cell counts once per UTC day. Full source hashes become known at
EOF; no raw source record needs to be inserted before that point.

## Pilot and limits

- First selection: MODIS NRT then Suomi-NPP NRT, filtering MODIS to Aqua.
  These two files total 79,036,082 bytes (about 75.4 MiB).
- Proposed selection: [2026-09-01,2026-09-02) and pilot South America rectangle
  [-60,-15,-59,-14]. This is not a national boundary or coverage claim.
- NOAA-20/21 NRT remain later source selections. Archive CSVs remain eligible
  but deferred until their schemas/years and larger scan settings are reviewed.
- Transfer limits: 80 MiB/file, 256 MiB/run including retries. The four NRT CSVs
  fit together without retries. Never silently skip an explicitly selected file.
- Chunk 64 KiB; batch at most 1,000 transient rows; field 64 KiB; logical record
  at most 1 MiB. Bound distinct selected cell/day memberships at 100,000/run.
- The old 100,000 retained-row cap is not used on this processed-only path.
  Full scans can contain more raw rows without increasing saved unique cells.
- Saved budget 500 MiB; temporary budget 2 GiB; map response at most 10,000 cells.
  Exceeding a cap fails the run, not a partial successful publication.

Unknown CSV ordering requires reading to EOF to find all selected records.
Do not stop at the first out-of-window date. A byte-range preview is not a
complete dataset or a date query. Full scan consumes network bytes even when
few cells are retained. Large archive scans require explicit transfer settings.

## Runtime access and source checks

Use existing httpx with Google Drive API v3. The chat connector confirms
folder access here; it does not supply the Python process with OAuth access.
Runtime preflight requires a short-lived token via GOOGLE_DRIVE_ACCESS_TOKEN
with permission to read the selected files. If unavailable, report the access
gate and stop before content reads. Never persist credentials, Authorization
headers, signed URLs, or browser cookies. No FIRMS key/request is needed.

List all pages of each child folder and select only real stored CSVs by suffix
and MIME. Ignore ZIPs, notebooks, other non-CSV files, and shortcuts before
content reads. Process one selected file at a time; no background service.
Use authenticated `files.get?alt=media` with TLS checks and identity encoding.
Never forward credentials to an untrusted URL or redirect host. Reject HTML
login responses even if HTTP returns 200.

Before/after streaming, verify file identity, size, modified time, version or
head revision, and available checksums. Hash full uncompressed source bytes
with SHA-256 while parsing. At EOF, check length/checksums and unchanged source
identity. A missing stable version/checksum verification is an explicit input
gate, not proof of a fixed source. Record observed version labels separately
from product assumptions. The VIIRS bright_t31 alias remains unverified.

## Proposed signatures and temporary files

`app/drive.py` owns source access; `app/cells.py` owns grid/summary rules.
Reuse `app/sources.py` checks for header, aliases, coordinates, and UTC dates.
Do not create persisted ObservationRecord objects or use source_file tables.

```python
list_drive_csvs(folder_id: str, *, client: httpx.Client) -> tuple[DriveFile, ...]
scan_drive_csv(file: DriveFile, *, client: httpx.Client, grid: GridSettings,
               area: AreaRecord, start_date: date, end_date: date,
               platforms: tuple[str, ...], maximum_bytes: int,
               maximum_memberships: int) -> ProcessedSource
```

DriveFile holds ID, name, MIME, size, modified time, stable version, checksums.
ProcessedSource holds source identity/full hash, grid/area/filter identity,
checked daily unique cell sets, bytes/row counts, and verification evidence.
The scan returns only after EOF checks succeed. No raw rows or original row-ID
arrays are returned or saved. Source original download time stays unknown;
Drive import time and modified time are not NASA download times.

Add --drive-folder-id to prepare_data.py, exclusive with --input-csv. With no
new input selector, keep the legacy CLI path isolated. Explicit settings hold
selected file IDs, source mappings, dates, area, and budgets; never infer source
identity just from a folder name.

Optional restart files under data/staging/drive/ are processed only:
- <file-id>-<version>-<selection-hash>.cells.json: verified day → cell-ID sets.
- progress.json: completed identities, processed checkpoint hashes, and byte counters.
- .part: incomplete processed checkpoint writes; never eligible for reuse.

Geometry can be rebuilt from cell IDs and frozen grid settings. The reducer
assigns a row before area-center filtering, so it retains full selected cells
including relevant detections outside the area outline. Do not enumerate or
store the empty world grid. Missing input and no detections remain distinct.

## Failure and restart

Keep an in-memory run byte counter including failed attempts. On 401, stop for
renewed access; distinguish permission-denied 403 from retryable quota errors.
Retry 429/temporary 5xx at most twice with bounded Retry-After waits. Restart
an interrupted file at byte zero with empty per-file sets. Do not persist or
resume from arbitrary CSV byte offsets. UTF-8 and quoted records can span chunks.

Reuse only completed processed checkpoints matching source version, selection,
grid, and checkpoint hash. Union each completed set once. If any selected file
fails, do not publish the release. Publish both tables and verified metadata
only after all selected streams succeed. Remove only this run's temporary
processed checkpoints after check_results.py passes.

Source manifests contain file IDs, versions, full hashes, filter rules,
row/byte counts, catalog/grid identity, and processing code version. They
contain no raw data and no per-observation selection list. The dataset must
remain usable when Drive is unavailable. Rerunning raw analysis later requires
access to the recorded source version; a hash does not guarantee its availability.

## Tests and execution order

Use Phase 1.3 (discovery/access), Phase 2.2 (stream reducer), and Phase 2.3
(summary union) in the main detailed checklist. Extend existing source tests
for pagination/exclusions, chunk boundaries, quoted CSV newlines, empty input,
changed version, malformed rows, token failure, retry accounting, and caps.
Extend the existing count test for A/B + B/C = 3. Keep at most 30 cases.

The pilot streams the small MODIS/Suomi NRT pair, writes only the two processed
tables, then reopens the API with Drive/FIRMS blocked. Verify shapes and count,
disk use, processed membership count, memory, elapsed time, and offline reads.
Full byte completion does not prove sensor coverage or national completeness.

References: [Google downloads](https://developers.google.com/workspace/drive/api/guides/manage-downloads)
and [file metadata](https://developers.google.com/workspace/drive/api/reference/rest/v3/files).
Runtime access, full source content, and preprocessing remain untested here.
