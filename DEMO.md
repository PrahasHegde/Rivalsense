# RivalSense demo handoff

Prepared 15 November 2026. Work is on **feature/hackathon-demo** in the separate worktree `C:\Users\steev\AppData\Local\Temp\RivalSense-demo-20261115`. Open this folder to use these changes. The original `feature/trusted-price-history` worktree, commits and pending changes were preserved. This temporary folder should be backed up before Windows cleans temporary files. A local demo commit is being prepared for review. Nothing has been pushed, merged or deployed.

## Audit and implementation

The existing React 19/Vite frontend had Google OAuth and session handling, but its product action was not connected to FastAPI and its dashboard was a placeholder. Its Supabase and validator imports were absent from package dependencies. The FastAPI application already provided authenticated product extraction, identity-aware competitor comparison, tracking, quotas, signed recording and extensive offline tests. These services were reused. No challenge brief was found in the repository or immediate surrounding workspace by filename search; the supplied judging priorities guided this implementation.

Context.dev's installed SDK supports the Answers API. Two bounded live calls using the existing backend credential succeeded: a sourced answer about Microsoft's founders and a Books to Scrape product extraction. The provider credential worked at the time of these probes. This does not establish that every earlier failure had the same cause. Missing frontend dependencies, missing frontend-to-backend wiring and the existing database-backed quota dependency were concrete integration obstacles.

The workspace now has sourced general research, suggested questions, cancellation and progress states, real product extraction/comparison forms, a confirmed-price chart, account-scoped browser research snapshots, optional cloud research history, existing price-history reads, and a hypothetical gross-profit calculator. Unknown prices and missing metadata remain unknown. Current-session results, historical snapshots and a dated verified example are labeled separately. No automatic capture or alert controls were enabled.

## Local configuration and startup

The isolated backend and frontend now have private, Git-ignored local configuration. The frontend contains only the validated public Supabase URL and anon key under `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`. The backend uses `RIVALSENSE_READ_BUDGET=local`, `RIVALSENSE_RECORDING_ENABLED=false`, and `RESEARCH_HISTORY_ENABLED=false`. No database migration is required for research.

1. Privately check that frontend and backend point to the same intended Supabase project. Keep Google OAuth configuration as it is; confirm the existing allowed redirect includes the origin you use. Do not paste credentials into chat.
2. `frontEnd/.env.local` is configured. Keep `VITE_API_BASE_URL` empty for the local Vite proxy. Context.dev credentials belong only in `Backend/.env`.
3. Without the unfinished database quota migration, read requests need an explicit **local demo** configuration in the isolated backend: `RIVALSENSE_READ_BUDGET=local`. Keep `RIVALSENSE_RECORDING_ENABLED=false` and `RESEARCH_HISTORY_ENABLED=false`. This opt-in limiter affects only research/extraction/comparison reads; it does not bypass trusted capture controls. Defaults remain database-backed and fail closed.
4. Local limits are initial settings: `RIVALSENSE_READS_PER_MINUTE=10`, `RIVALSENSE_GLOBAL_READS_PER_MINUTE=60`, `RIVALSENSE_READ_CONCURRENCY=2`. Use one backend process. Charges count attempted requests, including failures; comparisons charge by URL. This is not a distributed production quota.

An optional `Backend/scripts/configure_demo.py --source "<original repository folder>" --local-reads` helper prepares only the isolated ignored files and refuses mismatched effective frontend/backend projects or an existing frontend `.env.local`. It was **not run**. Review it before choosing to use it.

For an ordinary development installation, install Python requirements in a virtual environment and run these in two terminals:

```powershell
# Terminal 1, from this worktree
cd Backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2, from this worktree
cd frontEnd
npm.cmd ci
npm.cmd run dev
```

Open `http://localhost:5173/`. Vite forwards `/api` to `127.0.0.1:8000`; FastAPI defaults allow localhost and 127.0.0.1 on port 5173. An existing `CORS_ORIGINS` environment value overrides defaults and must include the chosen browser origin. Use Node 24 ARM64 (tested) or a version supported by Vite 8. Use `npm.cmd` on Windows if PowerShell blocks `npm.ps1`; no execution-policy changes are needed.

On this machine the original repository's existing `Backend/.venv/Scripts/python.exe` was used with the isolated worktree as the working directory. A checksum-verified Node 24.11.1 ARM64 runtime is available at `C:\Users\steev\AppData\Local\Temp\rivalsense-node\node-v24.11.1-win-arm64`; add that directory to the terminal's PATH if Node is not otherwise installed.

## API contracts

All research and price endpoints require `Authorization: Bearer <current Supabase access token>`. The centralized frontend client obtains the session, refreshes expiring tokens and reports unauthorized responses. No provider credential is sent to React.

`POST /api/ai/ask` accepts exactly `{ "question": "Who founded Microsoft and when?" }`, with a trimmed question of 3â€“2000 characters. Its response is:

```text
question: string
answer: string
keywords: string[]
sources: { title: string, url: string, publisher: string|null, published_at: string|null }[]
research_data: { facts: {label: string, value: string, source_url: string|null}[], uncertainties: string[], evidence_note: string }
status: "completed" | "partial" | "insufficient_evidence"
retrieved_at: ISO-8601 timestamp
persistence: "not_configured" | "saved" | "unavailable"
```

Sources come from Context.dev's actual `sources` field, not model-invented URLs. The SDK provides URL citations, so hostname titles are used and unavailable publisher/date metadata remains null. Facts link only to returned citations. Provider citations are attribution, not independent verification of every assertion. No-source responses become insufficient evidence. Provider/configuration failures return errors, never the saved example automatically. Provider timeout is 504; invalid/unavailable provider responses are 502/503; auth is 401, validation 422 and quota 429.

`GET /api/ai/history` returns `{ "items": [], "status": "not_configured" }` until explicitly configured. When enabled it returns the owner's latest 20 cloud rows and status `available`.

Existing `POST /api/prices/extract` accepts `{ "url": "https://public-product-page.example/path" }`. Its unchanged response has `status` (success/partial/failure), nullable `product_name`, `brand`, `price`, `currency`, `availability`, `source_url`, `observed_at`, and nullable `error`.

Existing `POST /api/prices/compare` accepts `product_name`, nonnegative `selling_price`, three-letter `currency`, optional `brand`, `sku`, `model_number`, and 1â€“5 `competitor_urls`. It returns `status`, reference product/price/currency, `observed_at`, `competitors`, `comparable_count`, `lowest_competitor_price` and `lowest_competitor_source_urls`. Each competitor includes extraction status/error, source/time, identity matching status/reason, price/currency, comparable flag/reason and price difference. Decimal money is serialized as JSON strings. Missing identity evidence is shown as needs review, not silently compared. Full schemas are in `Backend/app/schemas/comparison.py` and OpenAPI at `/docs`.

## Database work still requiring separate review

No database migration or write was executed. The unfinished `PROPOSED_price_history.sql` remains untouched by this demo work and must not be applied to make the demo work. Its inherited fingerprint remains `d2555d6d4d12639ad1d62045bb46118a2f0dde0feac583d3598e819e434401b3`. Alerts stay disabled. Existing history reads remain subject to owner RLS and may show a configuration error or empty state if unavailable.

`Backend/migrations/PROPOSED_ai_responses.sql` is an **optional, unexecuted proposal** for persistent general research. First obtain separately approved read-only metadata to establish whether an equivalent research table already exists; the available historical inspection exports do not establish the current live schema. The proposal aborts if it detects an equivalent table. It proposes one owner-scoped table, authenticated SELECT/INSERT policies and a user/time index. Client notes are not trusted price observations. Its RESTRICT foreign key preserves saved research and would block deleting an owning auth user while rows remain; retention/deletion behavior requires separate review before approval. Research answers work without this migration; persistence failures do not discard answers. Do not set `RESEARCH_HISTORY_ENABLED=true` until the schema, grants and RLS have been reviewed and tested.

## Verification and evidence classification

| Check | Result and scope |
| --- | --- |
| Backend offline suite | 107 passed; socket/DNS guard, no integration suite or DB connection |
| Frontend production build | Passed, Vite 8.3.8 |
| Frontend lint | Passed |
| Frontend node tests | 6 passed: Bearer forwarding, no-session rejection, refresh, errors, safe links, calculator |
| Render checks | App shell and saved/example provenance passed |
| Headless browser | Signed-out real app and static dashboard at 1440px/390px; no runtime errors or horizontal overflow |
| Local HTTP routing | Backend health 200; requests through Vite to research/extraction without auth returned 401 |
| Context.dev live research | Microsoft founders answer returned Bill Gates/Paul Allen and 1975 with a source |
| Context.dev live product extraction | A Light in the Attic returned 51.77 GBP on the probe; not a guarantee of today's price |
| Google sign-in / full authenticated flow | **Not verified**; local frontend configuration and interactive user session still needed |
| Supabase persistence / PostgreSQL concurrency | **Not run**; separate SQL approval/integration stage required |

The live probes were recorded at `2026-11-14T22:55:21.859789+00:00`. `frontEnd/public/verified-example.json` is a dated real saved answer, explicitly selected by the user and labeled NOT LIVE. Offline test fixtures and static layout props are synthetic test inputs, not observations. Calculator values are hypothetical estimates. The app does not populate overview cards with invented business metrics.

Repeat checks with:

```powershell
cd Backend
python scripts/test_offline.py
# In frontEnd, using Node on PATH:
npm.cmd test
npm.cmd run lint
npm.cmd run build
node scripts/render-layout.mjs
node scripts/verify-layout.mjs
node scripts/verify-layout.mjs http://127.0.0.1:5173/
```

The last two commands use an isolated temporary headless Chrome profile and require Chrome at the script's documented Windows path. They do not sign in. `Backend/scripts/diagnose_context.py` reports configuration presence without values; `--live` explicitly spends provider credits on the two bounded probes. It never enables recording. Do not repeatedly run paid live probes unnecessarily.

## Three-minute walkthrough

1. **0:00â€“0:25:** Open RivalSense, sign in using the existing Google flow, show the real empty/account counts. Complete this smoke test privately before judging.
2. **0:25â€“1:10:** Ask who founded Microsoft and when. Show the returned answer, timestamp and clickable provider sources. Explain that live web evidence also supports company and market research. A current EV question can be tried if latency/credits permit; never promise a particular answer.
3. **1:10â€“2:05:** Extract a public product URL, for example `https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html`. Show the actual price, source and time. Compare a known matching product if identity evidence is available; acknowledge needs-review results honestly. The chart shows only confirmed same-currency comparisons.
4. **2:05â€“2:35:** Enter hypothetical selling price 20, cost 12 and units 100. Explain the estimate: gross profit 800 and margin 40%, before expenses/taxes.
5. **2:35â€“3:00:** Reopen a saved research snapshot and point out NOT LIVE. Explain research plus competitor evidence plus potential financial impact. If the provider fails, show the visible error, then explicitly choose the saved verified example and disclose its date.

## Remaining issues by severity

1. **Demo blocker:** Configure the isolated frontend and explicitly choose the bounded local-read mode, then test a real Google session and authenticated research/extraction in the browser. This has not been completed or silently assumed. Check redirect allow-list privately if Google redirects fail.
2. **Demo risk:** Provider latency, credits and external sites can vary. Live probes succeeded, but availability is not guaranteed. Source citations do not independently establish each fact. Use the labeled saved example only as a disclosed fallback.
3. **Deployment blocker:** The demo limiter is process-local, not durable/distributed. Trusted recording/alerts remain unfinished and disabled. Real PostgreSQL RLS/grants/signed RPC/retry/concurrency/rollback/quota validation is still required separately.
4. **Optional capability:** Cloud research history needs equivalent-table inspection, SQL review and RLS tests. Browser snapshots are local to this browser/account and may contain sensitive research; use a private demo profile and clear site storage after use.
5. **Follow-up:** A deployed frontend needs an explicit API URL, its origin in CORS and correct OAuth redirects; these changes have not been deployed. Full accessibility and authenticated mobile interaction testing remain to be done.

Context API references: [Answers API](https://www.context.dev/answers-api), [official documentation index](https://docs.context.dev/llms.txt). No separate LLM provider or model credential was introduced.

## Research API diagnosis (15 November 2026)

The reported unreadable response was reproduced as `POST http://127.0.0.1:5173/api/ai/ask` returning HTTP 502, `text/plain`, and an empty body while no FastAPI server was listening on port 8000. Vite already forwarded `/api` to the correct target. Start both servers using the commands above. After FastAPI started, the same proxied request without authentication returned the expected HTTP 401 JSON error. The frontend now explains non-JSON proxy failures without exposing raw response bodies.

A live call through the existing research service and Context.dev returned a completed answer and a public source. Frontend API tests (8), backend research tests (12), and the production Vite build passed. Frontend and backend Supabase URLs match. Browser automation was unavailable during this diagnosis; the user subsequently confirmed the signed-in browser round trip and clickable sources. No auth bypass was added and no database changes were made.
Follow-up dashboard verification: backend access logs showed two authenticated `POST /api/ai/ask` requests returning HTTP 200. An isolated React form test replayed the genuine `Backend/research-live.local` provider response using test-only authentication and CDP response interception; it verified form submission, Bearer-header construction, answer text, and clickable source links. This is a response replay, not a signed-in end-to-end browser test. Before the visibility change, the answer panel began at y=783 in a 900px viewport. Results now appear before suggestions, receive focus, and scroll into view on completion. Desktop and mobile checks passed (panel y=63 and y=140). The user subsequently confirmed that the answer and clickable sources appear in the authenticated Chrome dashboard.
