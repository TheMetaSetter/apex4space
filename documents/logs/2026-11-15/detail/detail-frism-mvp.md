# Frism MVP checklist

## Pass 1
- [x] Select North America; add valid country catalog and search.
- [x] Preserve read-only database; reuse daily endpoints.
- [x] Add shared yearly maps, monthly counts, year stats and paging.
- [x] Mark incomplete years and missing data; defer Parquet.

## Pass 2
- [x] Reuse plain web stack and WebGL cell rendering.
- [x] Apply Frism logo and green, cream, orange palette.
- [x] Build Explore, Compare, Calendar frames.
- [x] Shared scales, linked views, calendar drill-down, year paging.
- [x] Panel toggles, responsive tabs, reduced motion; only stats scroll.
- [x] Explain 10 km grid, unknown coverage and polar display limits.

## Pass 3
- [x] Local Gemma chat with free questions and three prompts.
- [x] Validated data requests, shared queries, context and provenance.
- [x] Missing-data and Ollama failure states; paged answers.
- [x] Verify database counts, leap years, paging and chat.
- [x] Verify frames, panel controls, keyboard and no-scroll layout.
- [x] Write setup and reuse guide.

## Results

- 44 tests passed. JavaScript syntax check passed.
- Real 2024 yearly total agrees with existing daily API: 698,410 cell-days.
- 2024: 68,785 unique active cells; peak 2024-05-02, 4,798 cells.
- 2025: 69,103 unique active cells; 654,626 cell-days.
- Desktop 1135x852 and phone 390x844 checked. Body matches viewport;
  filters fit their bounds after compact spacing fixes.
- Calendar shows 1,096 days for 2023–2025, including leap day.
- Calendar leap-day click opened Explore on 2024-02-29.
- Panel close/reopen, shared comparison view, mobile tabs and chat failure state checked.
- Published SQLite files were not modified; queries open them with mode=ro.
- Local chat uses fixed validated intents and read-only functions. Tests use a
  model stub to check database context, follow-up history and answer failures.

## Live model dependency

- [x] Verify a live gemma4:e2b answer (completed in the later global-range check). Ollama is not installed on the normal
  command path and nothing responds at 127.0.0.1:11434. No model was downloaded.
  Backend integration and offline display are complete; live generation is
  not claimed. Start Ollama and pull gemma4:e2b using web-app/README.md.

Setup, query fields and reuse notes are in web-app/README.md. Future Parquet,
other release routing, harmonization, anomaly claims and drawn areas stay deferred.

Follow-up: live Gemma range comparison verified on 2026-11-15; see detail-global-ranges.md.
