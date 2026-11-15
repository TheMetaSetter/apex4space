# Notion review for time-series-api v0.4

Date: 2026-11-13. Result: specification edited; no product code or science run.

## Work checklist

- [x] Phase 1 — Read sources with Notion, Drive, and local file tools.
  - [x] Find the project page and read its text.
  - [x] Follow its child pages and read every row of its four data sources.
  - [x] Read the pages behind those rows.
  - [x] Resolve and download all 26 attached files to a temporary directory.
  - [x] Inspect all 25 images and screen the leadership PDF for relevance.
  - [x] List the linked Drive folder and its four source subfolders.
  - [x] Read the notebook code, saved text outputs, and four README files.
- [x] Phase 2 — Compare sources with the spec using Markdown and file reads.
  - [x] Compare v0.3, the ingestion brainstorming note, and the tree proposal.
  - [x] Separate team proposals from evidence and explicit user choices.
  - [x] Check NASA field/README pages and OpenLayers docs with web tools.
  - [x] Choose small additions and retain unresolved science questions.
- [x] Phase 3 — Edit and review using file patches and Python.
  - [x] Update the spec to v0.4 with source links and a naming table.
  - [x] Add OpenLayers and the saved small API sample from user follow-ups.
  - [x] Review language, links, reference IDs, JSON, and preserved contracts.

## Source coverage

Root: [apex4space](https://www.notion.so/40f07acf01e080ea93dbd6a6b3c07551).
The exact-title search also found the team-members database named apex4space;
its parent is the project page above. Both were read.

Read 18 pages and five database blocks. The five blocks use four data sources;
the Gantt chart is another view of tasks. Each row query returned
`has_more=false`. No omitted-block warning was reported by page fetches.

| Pages or database | What was read | Use in spec |
| --- | --- | --- |
| Project root | Challenge, proposed event grouping/schema, two work phases, cloud/Arrow suggestions, links, scope TODOs | Clarify scope and defer added tools. |
| Pre-event meet-up | Text and 13 screenshots | Demo, credits, AI-use disclosure, public access. |
| Agenda | Empty content | No added requirement. |
| Internal training documents | Project management, time-series topics, web links | Training material is not a stack decision. |
| Collective leadership | Page, five images, attached PDF screened through abstract and discussion/limits | No API/science requirement derived from this paper. Not a full paper-method audit. |
| Wasm and Chromium | Page and one image | No need for browser-side science or Wasm. |
| Elixir; Hologram | Both linked-resource pages | No language/framework change. |
| Bach's space | Fire direction and country fire-rate ideas | Keep out of the calendar MVP. |
| Team-members database | Four rows and four member pages | Existing roles; no new person assignment inferred. |
| Problem 1 roles | Two rows and their empty role pages | Delivery owner/reviewer remain unassigned. |
| Problem 2 roles | Two rows and their empty role pages | Same. |
| Tasks and Gantt | One shared empty task row and its page | No schedule or completed work inferred. |

Attached-file inventory below follows page order. Each image was visually
inspected. Repeated `image.png` names refer to separate Notion blocks.

| Files | Parent | Content |
| --- | --- | --- |
| 01 | Root | Illustrative graph communities, not a fitted fire model. |
| 02 | Root | Pixel size/area diagram. |
| 03–04 | Root | Fire-map examples from the challenge video. |
| 05 | Root | Satellite image example. |
| 06 | Root | FIRMS map screenshot. |
| 07–08 | Meet-up | Local-event agenda screenshots. |
| 09 | Meet-up | Impact, creativity, validity, relevance, presentation. |
| 10 | Meet-up | Award categories. |
| 11 | Meet-up | Submission window slide. |
| 12 | Meet-up | Public project/demo link; slide/video limits. |
| 13 | Meet-up | Demo, language, access, and media guidance. |
| 14 | Meet-up | Slide content guidance. |
| 15 | Meet-up | Short-video structure. |
| 16 | Meet-up | Permitted AI-tool use and disclosure. |
| 17 | Meet-up | NASA data and other source/tool credits. |
| 18 | Meet-up | Collaboration and learning. |
| 19 | Meet-up | Judging stages. |
| 20–22 | Leadership | Task/social/external roles; illustrative collective/distributed roles. |
| 23–24 | Leadership | Teamwork findings and time-zone example. |
| 25 | Leadership | Chamberlin et al. (2024), DOI 10.1002/job.2774, 25-page PDF. |
| 26 | Wasm and Chromium | Browser process/memory diagram. |

The event slides show November 14–15, 2026 and a 23:59 local submission
closing time on November 15. The spec links the slides and requires checking
current instructions rather than treating a screenshot as a live deadline.

## Linked Drive files and limits

[Data folder](https://drive.google.com/drive/folders/1_RbaB1o7lrmOlzsp8CGq34Oe_rQ_lKMc):
one notebook, four ZIPs, and four source folders. Each source folder contains
one README, one archive CSV, and one NRT CSV. All listed entries fit within
the connector's 100-child listing limit; no pagination was indicated.

| Source | Archive CSV bytes | NRT CSV bytes |
| --- | ---: | ---: |
| MODIS M-C61 | 1,408,411,858 | 14,333,689 |
| Suomi SV-C2 | 2,947,153,227 | 64,702,393 |
| NOAA-20 J1V-C2 | 1,753,113,864 | 70,265,198 |
| NOAA-21 J2V-C2 | 681,199,204 | 67,723,546 |

Read all 19 notebook cells and saved text outputs, without running its code.
Read all four README files; each links to the same NASA download README,
which was also read. The notebook shows archive sample rows with `type`,
mixed MODIS version values, and NOAA-21 dates needing a product/date check.
Some saved outputs remain under commented source; they are recorded outputs,
not proof that the current code recreates them.

The CSV and ZIP bodies were not downloaded or rescanned in this review.
Archive CSVs total about 6.32 GiB, beyond the spec's 2 GiB temporary budget.
ZIPs were inventoried, not opened. The v0.3 NRT scan claims were retained as
earlier recorded checks, not repeated checks. Thus this is full coverage of
the exposed Notion page tree and attachments, with partial content coverage
of the linked bulk data. It is not a claim to have read all linked data rows
or every external tutorial, website, repository, and video.

## Decisions and checks

Compared three paths: import full archives; run live ingestion; save a small
API sample. Chose the saved sample: less storage and fewer moving parts.
The user explicitly supported that choice and chose OpenLayers. No real-key
FIRMS request was made. Exact rectangles and available windows remain unset.

Added type/confidence rules, unmatched-record retention, source-date checks,
release repeatability, map coordinate handling, and a small deployment/demo
handoff. Event clustering and impact/prediction stay outside the MVP.
The spec records these as choices; Notion was not edited.

NASA/OpenLayers pages were read through web tools. The official challenge
URL returned HTTP 502 on this pass; its current text was not reconfirmed.
The NASA team discussion was read as context, not as validated science.
No earlier local v0.1/v0.2 spec text was found. The structure prompt referred
to by repository rules is missing.

Attachment downloads first failed inside the network sandbox. An authorized
network retry fetched all 26. The project Python lacked Pillow; the bundled
Python runtime was used for image contact sheets. No project dependencies
were installed. Signed download URLs were not written into the repository.

Verification is a document review, not an API or scientific runtime test.
