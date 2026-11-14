# time-series-api Implementation Plan

Date: 2026-11-14. Status: ready to start engineering; science tasks have gates.

**Goal:** Build the local data API, starting with one saved source-only sample,
then publish harmonized history only after independent tests pass.

**Architecture:** One Python app and one SQLite database. Ordinary functions
prepare data offline and serve fixed releases. OpenLayers stays in web-app.

**Tech stack:** Python 3.13, FastAPI/Pydantic, sqlite3/csv, Uvicorn, Pytest,
HTTPX; scientific/native-file libraries only when the selected inputs need them.

**Spec:** [development spec](../../../specs/time-series-api-devspec.md),
[interfaces](../../../specs/time-series-api-signatures.md), and
[tree](../../2026-11-13/structure/time-series-api-directory-tree.md).
Current-state evidence: [research](../research/research-time-series-api-implementation.md).

## Request and scope

Read prompts 1 → 2 → 3 → 4 and write a detailed implementation plan.
This planning turn creates documents only. The user accepted the design
before requesting details; another design-permission round is not needed.
The detailed execution checklist is written in the fourth prompt's output:
[detail-time-series-api.md](../detail/detail-time-series-api.md).

Include all eight endpoints, source imports, release storage, scientific
checks, history, security, and web handoff. Exclude polygon request inputs,
event clustering, tactical alerts, forecasting, full archive imports,
TimescaleDB, queues, and a new frontend build. Integration with the web
developer is included; their app source is outside this backend plan.

## Global constraints

- Follow documents/specs as the source of truth; keep current names.
- Keep code files below 500 lines and functions below 50 lines.
- Use the repository `.venv/bin/python`; preserve unrelated work.
- Keep saved data/database/reports within 500 MiB and temporary data within 2 GiB.
- Use 1–5-day provider windows, the stated 5,000/600-second transaction limit,
  and the proposed pause at 4,000; check actual provider status before batches.
- Default pages to 1,000 and cap them at 10,000.
- Unknown values stay null; source detections are not real fire-event counts.
- Require five usable earlier years for published historical comparisons.
- Do one real end-to-end pilot before expanding. Never fit inside HTTP calls.
- A source-only demo is not a finished harmonized MVP.

## Review focus

| Likely failure | Expected behavior | Owning detail task |
| --- | --- | --- |
| Chunked/oversized request without Content-Length | 413 before parsing; safe JSON error | T5 |
| NRT replacement after a user starts paging | Old release and cursor still return the same source rows | T2, T5 |
| Tiny box with no cell center | Spatial-support warning, not zero estimated fire activity | T4 |
| Source CSV has no rows but no coverage proof | Keep unknown coverage; do not declare a clear-sky zero | T3, T4 |
| Export crosses a limit after some rows | Error before download headers; no successful truncated file | T6 |

## Selected path

| Option | Benefit | Cost | Decision |
| --- | --- | --- | --- |
| Small saved API sample | Small disk use; repeatable web work | Limited scientific scope | Selected |
| Import all archives | Broad historical inputs | Exceeds current temporary budget | Not first |
| Live continuous ingestion | Frequent updates | Adds failure/recovery and hosting work | Deferred |

## Ordered phases

- [ ] P1 — Establish typed contracts and safe release storage: T1–T2.
- [ ] P2 — Complete a fixture-backed source-only API and early web examples: T3–T6.
- [ ] P3 — Run one real saved-sample flow: T7–T8.
- [ ] P4 — Check native coverage, FRP, and count methods: T9–T11.
- [ ] P5 — Publish only the historical scope that passes: T12.
- [ ] P6 — Finish web acceptance and, if required, a public demo: T13–T14.

Each phase depends on the previous phase's checks. The web developer can use
the fixture/source-only API after P2 while science remains pending. P4 may
stop with a failed method; do not skip it and claim P5 is harmonized.

## Gates and unknowns

No engineering decision blocks T1–T7. Pilot area and limits are explicit
proposals in the detail plan. T8 requires a private provider key and actual
availability. T9 requires matching native inputs and a verified reader.
T10–T11 require test definitions before fitting and may reject a method.
T12 requires independent test support and five baseline years. T14 requires
a chosen host and a deployment request. These are task prerequisites, not
claims that all remaining work is ready to execute now.

No learned model interface or scientific threshold is silently filled in.
The relevant task must record its evidence in settings/report and update
the canonical spec before publishing a new scientific claim.

## Recovery and final result

Keep old releases and source records. Stop serving for publication; expose
a release only after files exist and the database transaction commits.
Recover by selecting the last checked release. Do not delete broad data trees.
The final review checks data, science, API, user workflow, and disk/time
limits separately. A passing unit test suite alone does not finish this MVP.
