# Date ranges and global Frism

## Pass 1
- [x] Add shared range request, paging, stats and daily counts.
- [x] Include both chosen dates; validate full release bounds.
- [x] Reuse range aggregation for daily and year views.
- [x] Test leap days, boundaries, empty and invalid dates.

## Pass 2
- [x] Add Explore From/To controls and one-day shortcut.
- [x] Add independent comparison ranges with year shortcuts.
- [x] Preserve overlap; show duration and average daily cells.
- [x] Pass ranges into grounded chat.
- [x] Test overlap, separate, identical and unequal ranges.
- [x] Keep Frism style, toggles and no-scroll layout.

## Pass 3
- [x] Add global country/continent/World lookup from source codes.
- [x] Keep valid display outlines separate from name lookup.
- [x] Deduplicate country unions; reuse all views and chat.
- [x] Limit detailed map loading to viewport; keep global stats.
- [x] Test borders, date line, unmapped codes and global totals.
- [x] Benchmark day, year and full history; show explicit timeouts.
- [x] Publish checked global settings and preserve rollback.

## Results

- Date-range API: inclusive endpoints, full release bounds, whole-area totals,
  paged viewport geometry, duration and average daily cells. Legacy summaries
  keep their original excluded end-date rule.
- Explore and Compare controls verified with overlapping real ranges:
  North America 2024-02-27 through 2024-02-29 = 5,422 cell-days;
  2024-02-28 through 2024-02-29 = 3,366 cell-days.
- World lookup: 230 countries, seven geographic groups and World. No source
  code is unmapped. Egypt has no outline; its code/name queries remain valid.
- World 2024: 656,093 cells and 11,233,633 cell-days, 1.94 seconds locally.
- World leap day: 30,798 cells, 0.08 seconds.
- Viet Nam 2024: 3,634 cells and 71,684 cell-days, 0.24 seconds.
- Full world history: 1,397,448 cells and 150,115,992 cell-days, 27 seconds
  using year chunks; measured total process peak about 1.42 GB.
- Initial full-history single-scan aggregation hit its memory limit. The
  failure was explicit; year chunking fixed it without shortening the request.
- Independent per-month DISTINCT counts and independent unique grid counts
  agree with full-history totals. Checks and benchmark JSON files are beside
  this checklist. Source files and the Mercator grid are unchanged.
- Only viewport details load at zoom >=2.5. World overview requests statistics;
  zooming in loaded 4,028 cells while retaining the full day's 20,872 total.
- Phone 390x844 body fits exactly; filter Fit button bottom 667.5 is inside
  panel bottom 696. Mobile Range B tab, summary toggles and form tested.
- Source snapshot identity is unchanged. Global metadata lives in
  data/areas/world/parquet-v1 and name lookup in config/global. North America
  rollback settings are saved in config/settings-north-america.json.
- Live Gemma comparison passed in 3.53 seconds with exact 5,422/3,366 results,
  both range sources, release identity and unknown coverage. Full live response
  saved in global-live-chat-check.json. Thinking is disabled for short planning;
  the JSON budget is 1,000 tokens. Selected UI ranges fill incomplete plans.
- Setup/API and rollback notes are in web-app/README.md. Original SQLite APIs
  remain available; new date-range web controls use Parquet.

Final verification: 57 tests passed, including cross-month/year queries and
incomplete model-plan fallback. JavaScript syntax check passed. New modules
meet the 500-line file and 50-line function limits. Viewport filtering compares
source grid indices directly, avoiding geometry conversion for off-screen cells.
Hidden mobile comparison panes request statistics only; selecting the pane
loads its visible geometry. Map zoom controls no longer sit behind the chat button.

Final regression suite: 58 tests passed after adding a selected-comparison
chat action. The demo button uses compare_selected=true with the current two
ranges, bypassing model date planning; free text still uses validated intents.
The action is covered by an identical-range regression test. Chat is available
from the header on all frames; Calendar sends its latest displayed year.

Final browser check on the running server: the header comparison demo produced
World 2024/2025 answers with the exact 656,093/659,783 cells and
11,233,633/10,088,765 cell-days. The World calendar rendered 1,096 days for
2023–2025. Its 2025 cards show 10,088,765 cell-days, peak month August
(1,090,055 cell-days), and peak day 2025-08-30 (42,816 cells).
Desktop body and viewport both measured 727x852. The global calendar tab is
left open as the deliverable, with the final server running at localhost:8000.
