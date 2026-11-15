# Free Vercel release

Use the current app. No object names change. Local data and local Ollama stay usable.

## Pass 1 — small app

- [x] Check the team: `thehien04s-projects`, Hobby, active.
- [x] Keep the plain web app and Python API. No new web framework.
- [x] Add a script that copies only code, maps, catalog and release notes.
- [x] Keep raw files, SQLite files, model weights, tests and logs out of the bundle.
- [x] Check the function budget. Linux dependencies: 176,450,856 bytes; deploy source: about 7.9 MB. Vercel accepted the Python build under its 500 MB limit.
- [x] Check hosted runtime memory. Highest measured peak: 274.7 MB, below 1.6 GB.

## Pass 2 — data and chat

- [x] Add a reader that downloads and checks one month, queries it, then removes it.
- [x] Union countries before counting cell-days. Keep the source grid.
- [x] Limit cloud map pages to 1,000 cells and responses to 2 MB.
- [x] Stop long queries with a clear error.
- [x] Add hosted chat with a zero-price model check and exact data fallback.
- [x] Save 54 common World and North America calendars.
- [x] Upload 313 checked Parquet files (802,362,812 bytes). Store count and size checked. No other Blob stores were present.
- [x] Check hosted model access. Vercel requires a credit card even for its zero-price model. The user chose database-summary answers instead. Hosted AI stays off; no credits, card or top-up were added.

## Pass 3 — test and publish

- [x] Pass 63 local tests, including hash failures, cleanup, body/page/response limits and cloud chat fallback. JavaScript syntax also passes.
- [x] Deploy previews from the prepared source folder.
- [x] Test first requests, dates, map pages, overlapping comparisons, calendar and chat. Counts match local references. First config request was about 4 seconds including CLI and network time.
- [x] Check memory, scratch space, data transfer and free quotas. SQL memory is capped at 384 MB; spill space at 256 MB; one download at 64 MB. A country/year test read 60,564,777 bytes. The all-date World request stopped safely after 50.53 seconds, after reading 112,993,826 bytes. Long ranges need shorter requests on this free setup.
- [x] Add and test shared platform rate limits. Active firewall version 3 allows 600 API requests per minute per IP. The temporary preview rule was tested with 14 HTTP 429 responses.
- [x] Publish after the free limits pass. Promote the tested production build and check the public site without cookies or bypass headers.
- [x] Record the public URL, release ID and rollback command below.

Vercel's connector kept returning 403 after two access approvals. The CLI reached the same approved team and confirmed Hobby. Use that exact team and existing project `apex4space`.

Choices considered: one bundled database is too large; a paid backend breaks the free-only rule; a thin Python function with Blob keeps the current code and fits the source-data storage allowance. Free quotas can pause the app.

## Check results

The checked release is `50589b4e46f939cc682ffb4e6bf940fad69e95e25a1a908a1074ab675adad721`, covering 2000-11-01 through 2026-11-11. All source files remain available; the timeout limits one cloud query, not the stored dates.

The catalog response is 1,529,196 bytes. A tested 1,000-cell page is 437,568 bytes. Display outlines are simplified for the cloud; data membership and counts are unchanged. File hashes in asset URLs prevent stale code and styles after updates.

The browser check confirmed visible hotspot cells, a calendar that fits the screen, and panels that open and close. The temporary browser-test server on port 8001 was stopped. The original local server on port 8000 was left running.

The shared preview rate test allowed 10 requests and returned HTTP 429 for 14 excess requests. The final 600-per-minute rule is active. The user explicitly asked the agent to publish this reviewed change, replacing the skill's manual handoff. The exact Vercel effects digest was approved and used. Local request body checks remain; cloud request rates are delegated to the shared firewall.

See [vercel-checks.json](vercel-checks.json) for small check results and the deploy-source hash. See [VERCEL.md](../../../../web-app/VERCEL.md) for reuse commands and rollback notes.

## Live release

- Public URL: https://apex4space.vercel.app
- Production build: `dpl_F13dyhkqAQDoA35wqFSUXfSnjJwh`.
- Build URL: https://apex4space-ciywq14b7-thehien04s-projects.vercel.app
- Public checks: home, health, catalog, hashed assets, North America range and the busiest-month summary all return correct results without sign-in.
- The main production alias is public. Preview and unique build URLs keep Vercel sign-in protection.
- Chat uses the database-summary mode chosen by the user. Hosted AI is off.

To return to this good release after a later deployment:

```sh
vercel rollback https://apex4space-ciywq14b7-thehien04s-projects.vercel.app --scope thehien04s-projects
```
