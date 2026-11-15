# RivalSense backend

FastAPI backend for Context.dev product extraction, comparison, and authenticated
Supabase product tracking, plus sourced AI research. The React/JavaScript framework and Google authentication are preserved. For the one-service Render demo, see [deployment instructions](../DEPLOYMENT.md).

Trusted history is prepared locally but is **not deployment-approved**.
The SQL in [PROPOSED_price_history.sql](migrations/PROPOSED_price_history.sql) is
a proposal only. Startup never runs migrations. Automatic alert creation defaults
to disabled independently of history recording.

Read the [API guide](docs/supabase-api.md) and
[security/deployment review](docs/recording-migration-review.md) before rollout.

## Local startup

From Backend, using the existing virtual environment:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Only if .env does not already exist:
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
~~~

Never overwrite an existing .env or commit credentials. Settings:
SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, CONTEXT_DEV_API_KEY, CORS_ORIGINS.
RIVALSENSE_RECORDING_SECRET is intentionally blank in the example.
RIVALSENSE_RECORDING_ENABLED defaults false; the former atomic-mode and
environment threshold settings no longer control recording.

The revised extraction endpoints require both Supabase authentication and the
proposed shared quota RPCs/private secret. Until those are provisioned through
a separately approved rollout, these endpoints fail closed rather than consuming
unlimited provider quota. Existing product/history reads use user-scoped RLS.

## Endpoints

- GET / serves React when FRONTEND_DIST is configured; otherwise it returns API information. /health checks process availability only.
- GET /docs exposes API documentation.
- POST /api/ai/ask accepts a research question and returns an answer with public source links.
- GET /api/ai/history is optional and returns not_configured while cloud history is disabled.
- POST /api/prices/extract accepts an HTTPS product URL.
- POST /api/prices/compare accepts reference product identity, selling price,
  currency, and up to five competitor URLs.
- Product/listing/history/alert endpoints are documented in the API guide.

Every /api endpoint requires Authorization: Bearer <Supabase access token>.
Extraction and comparison retain their existing calculation and response formats.
Comparison confirms identities conservatively, uses Decimal money, and does
not convert currencies or invent missing prices. Partial and failed extractions
remain explicit. Extraction numeric JSON output and comparison money strings
retain their previous formats.

Extraction's existing 400/422/502/503/504 outcomes remain; 401 and 429 are added.
Trusted recording additionally requires an Idempotency-Key UUID and migration
readiness. It returns database-authoritative history/change/alert decisions.

CORS defaults to localhost ports 3000 and 5173; set CORS_ORIGINS for deployment.
CORS is not authentication or rate limiting.

## Offline tests

~~~powershell
.\.venv\Scripts\python.exe scripts/test_offline.py
~~~

This runner blocks real socket connections, connect_ex, and DNS. Windows'
internal asyncio socketpair is allowed only during its own creation. Auth,
PostgREST, Context.dev, and public-URL lookups are mocked. No database or provider
credentials are needed. Existing extraction, comparison, SDK serialization,
URL safety, and route regression tests are retained.

These tests do not execute SQL. PostgreSQL role permissions, triggers,
transactions, locks, and concurrent quota enforcement need separate integration
validation before deployment.

## URL safety limits

Local preflight pins requests to checked public IPs and checks redirects.
Context.dev navigates independently: local checks and final-URL validation cannot
prevent every unsafe intermediate provider navigation or DNS rebinding.
Verify provider-side network restrictions before production exposure.
