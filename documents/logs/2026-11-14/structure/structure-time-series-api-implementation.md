# Implementation structure: time-series-api

Date: 2026-11-14. Status: derived from the user-accepted design; no code run.
Basis: [plan](../plan/plan-time-series-api.md),
[spec](../../../specs/time-series-api-devspec.md), and
[interfaces](../../../specs/time-series-api-signatures.md).
The user requested detailed planning after accepting the design. This file
records the phase order; it does not claim a new approval or completed work.

## Phases

| Phase | Result and scope | Depends on | Check and finish condition |
| --- | --- | --- | --- |
| P1 | Typed requests/settings; six-table release storage | Accepted spec/tree/interfaces | Invalid input rejected; save/read/rollback and old-release tests pass. |
| P2 | All endpoints work on invented source-only fixtures; early OpenAPI examples | P1 | Missing/zero, geometry, paging, export, errors, body/rate/CORS tests pass. |
| P3 | One real small API sample is saved, published, served, and downloaded | P2 plus private provider key and available dates | One exact area/date/platform combination passes the whole flow within budgets. |
| P4 | Independent FRP and count evidence on native coverage data | P3 plus matching native inputs | Reports state scope, targets, results, failures, and method decision. A failed method stops harmonized publication. |
| P5 | Checked history for a fixed release | Passed P4 method and usable historical inputs | At least five usable earlier years per offered comparison; source-transition tests pass. |
| P6 | Web developer accepts one full map-to-download flow; optional public demo | P2 for early handoff; P5 for a full harmonized MVP | Screen/download match; missing periods are visible; local or deployed smoke checks pass. |

P4 contains three ordered stages: native-input verification, FRP testing,
then count testing. P5 starts small and expands only after one checked
combination. P6's source-only handoff can happen after P2; final scientific
acceptance cannot.

## Tools and owners

Python/Pydantic own data contracts. sqlite3 owns storage. CSV/HTTPX handle
small source windows. FastAPI/Uvicorn serve saved data. Pytest owns automated
checks. Native readers and geometry tools are selected only after P4 inputs
are known. OpenLayers belongs to the web developer.

## Main risks and recovery

Missing provider/native data blocks the related data stage, not fixture-based
API work. A method failure keeps a source-only release useful but incomplete.
A failed publication leaves the prior release selected; remove only the
candidate's unused files after checking them. Extra services, wider downloads,
and real polygon inputs are outside the accepted MVP.

## Detailed expansion

The [detailed checklist](../detail/detail-time-series-api.md) keeps this order,
names each file and function, and lists checks before the next task starts.
All implementation items remain unchecked until executed and verified.
