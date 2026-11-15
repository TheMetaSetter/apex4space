# Current state for time-series-api implementation

Date: 2026-11-14, Asia/Ho_Chi_Minh. Read-only code research; no runtime build.
Branch: `anhkhoi-dev`. HEAD: `c3bf05efa0f0d0ec7e8be76d853a1e0ea8a62e66`.
The working tree has existing uncommitted files. HEAD alone does not contain
the current design documents.

## Question and finding

What exists today, and what must an implementation plan account for?
The API is designed but not implemented. No source execution path can yet
be traced. The design's proposed HTTP and offline paths are not runtime evidence.

## Evidence

| Source | Finding | Evidence class |
| --- | --- | --- |
| `documents/specs/time-series-api-devspec.md`, §§3, 9–12 | Small saved sample; separate science checks; six tables; eight endpoints; polygon support later | Documented requirements |
| `documents/specs/time-series-api-signatures.md`, §§2–10 | Types, calls, limits, release writes, HTTP shapes, security and web handoff | Proposed interfaces |
| `documents/logs/2026-11-13/structure/time-series-api-directory-tree.md` | Six app modules, three scripts, five test files plus fixtures | Proposed files |
| `time-series-api/`, checked with `rg --files` | Two tutorial notebooks and one sample CSV; no `.py` app or test files | Observed files |
| Sample CSV header | Native VIIRS names `bright_ti4`, `bright_ti5`; 6,077,404 file bytes | Observed header/size, not a full scan |
| `.venv/bin/python`, narrow module probe | Python 3.13.5; HTTPX and NumPy available; FastAPI, Pydantic, Uvicorn, Pytest, and pip absent | Observed environment |
| `command -v uv` | `/Users/conquerormikrokosmos/.local/bin/uv` exists | Observed tool path |
| `AGENTS.md`; `codebase_preferences.md`; `python_semantics.md` | Spec ownership, small files/functions, focused tests, one real pilot before expansion | Project rules |
| Prior Notion review | Bulk archives were inventoried, not rescanned; science still untested | Historical review, not current runtime proof |

## Configuration and interfaces

No application settings file, CLI parser, published release, or test suite
exists under time-series-api. Root `requirements.txt` is empty. Proposed
defaults are therefore design choices, not verified parser defaults.
No dependency install, provider call, model fit, or API test ran during planning.

The current contract keeps rectangle inputs and converts them to an internal
Polygon. Later polygon requests remain out of scope. The web app uses
OpenLayers; no frontend implementation is present in the inspected tree.

## Limits and unresolved evidence

Actual pilot source availability, keys, native coverage products, the count
method, historical support, and hosting remain unverified. They must be
explicit execution gates, not assumed inputs. Engineering can start with
invented fixtures and then one real source-only sample.

The old research note links a missing `preprocess_tabular.ipynb`; do not use
it as an active caller. The four numbered prompts were found under
`prompts/primitive_prompts/`, correcting the earlier note that their shorter
paths were missing. They were read in order 1, 2, 3, 4 for this task.

Keep all existing user edits, notebooks, and samples. No Git cleanup, commit,
external write, download, or source-code change is part of this planning turn.
