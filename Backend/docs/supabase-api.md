# RivalSense tracking API for Rebecca

**Migration revision:** [recording-migration-review.md](recording-migration-review.md)
supersedes the proposed atomic recording and permission design below. Neither
proposal is applied. Do not enable the old atomic-mode flag for the revised SQL.

This integration targets the setup SQL supplied by the owner. It has **not**
inspected or modified the live project. Mocked tests do not prove deployed RLS
policies or the proposed SQL function work. Compare the live schema with
`migrations/inspect_schema.sql` before approving any migration.

## Configuration and authentication

Use the existing `.env` values `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`.
Only the modern `sb_publishable_` key type is accepted; service-role/secret keys
are deliberately rejected. Rebecca's Google login is unchanged.

Every endpoint in this document requires:

```http
Authorization: Bearer <Supabase session.access_token>
```

Use the Supabase session token, not Google's provider token. The frontend keeps
responsibility for refreshing its Supabase session and supplying a current token.
The backend verifies the token using Supabase Auth `GET /auth/v1/user`; it does
not merely decode JWT claims. It forwards the same token and project publishable
key to PostgREST. Clients exist for one request only and never refresh or persist
sessions. Explicit owner filters supplement RLS; parent resources are checked
before creating children. Inaccessible resources return 404.

Do not send a `user_id` in JSON. The backend derives it from the verified user.
Never put keys or tokens in URLs, query parameters, logs, or screenshots. No raw
Auth, database, or Context.dev exceptions are included in responses.

The database dependency is Supabase's official `postgrest==2.34.1` package, with
HTTPX for Auth. Installing the full `supabase` package on this Windows ARM64 /
Python 3.15 setup failed because cryptography required an unavailable MSVC linker.
The smaller client installed successfully and `pip check` passed.

## Routes

| Method and URL | Body / result |
| --- | --- |
| `POST /api/products` | Product creation JSON; HTTP 201 product object |
| `GET /api/products` | Paginated array of owned products |
| `GET /api/products/{product_id}` | Owned product object |
| `POST /api/products/{product_id}/competitors` | Listing creation JSON; HTTP 201 listing object |
| `GET /api/products/{product_id}/competitors` | Paginated listing array |
| `POST /api/competitors/{listing_id}/observations` | No body; required `Idempotency-Key` UUID header; record-result object |
| `GET /api/competitors/{listing_id}/observations` | Paginated observation array, newest first |
| `GET /api/alerts` | Paginated owned-alert array, newest first |

Array endpoints accept `?limit=50&offset=0`; limit is 1–100, offset is nonnegative.
Ordering uses time descending, then UUID descending as a deterministic tie-breaker.
Concurrent additions can shift offset pages; these are not snapshot cursors.
UUIDs are required in paths. OpenAPI examples and schemas are available at `/docs`.

Existing `/`, `/health`, `/api/prices/extract`, and `/api/prices/compare` remain
unchanged and do not automatically store results. They retain their existing
authentication behavior. Only the new tracking endpoints require Bearer tokens.

## Add a product

```json
{
  "name": "Acme Mug M-100",
  "brand": "Acme",
  "sku": "M-100",
  "model_number": "M-100",
  "selling_price": "120.00",
  "cost_price": "70.00",
  "currency": "EUR"
}
```

Only name, selling_price, and currency are required. Brand, SKU, model number,
and cost price may be null. Product responses add `id`, verified `user_id`, and
`created_at`. Money is represented as decimal strings, never frontend binary
float calculations. The database's `numeric(14,2)` permits up to
`999999999999.99`; negative, non-finite, and more-than-two-decimal inputs are
rejected. Currency must contain exactly three uppercase letters.

## Add a competitor listing

```json
{
  "competitor_name": "Example Shop",
  "product_url": "https://example.com/products/acme-mug-m-100"
}
```

Responses contain `id`, `user_id`, `product_id`, `competitor_name`, `product_url`,
`is_active`, and `created_at`. The product URL uses the existing HTTPS/port/
credentials/public-DNS checks. Creating a listing does not scrape Context.dev.
Observing it later performs the existing redirect preflight and returned-URL
checks. The documented remote-browser safety limitations still apply.

Duplicate listing URLs for the same user and product return 409. Parent product
ownership is verified first. New listings default to active in the database.

## Observe a listing and retrieve history

```http
POST /api/competitors/<listing UUID>/observations
Authorization: Bearer <Supabase access token>
Idempotency-Key: <new UUID for this deliberate observation>
```

This endpoint makes a real Context.dev extraction and consumes credits. Do not
call it automatically in a frontend retry loop with a new UUID. Reuse the same
Idempotency-Key if the HTTP response was lost; a previously saved observation
is returned without another extraction. Different UUIDs intentionally append
new observations. Simultaneous requests may both start extraction before either
is saved; the primary key prevents duplicate stored observations, and the
proposed transaction prevents duplicate alerts. Provider calls themselves cannot
be rolled back or guaranteed exactly once.

Each saved observation contains:

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "user_id": "22222222-2222-4222-8222-222222222222",
  "listing_id": "33333333-3333-4333-8333-333333333333",
  "price": "110.00",
  "currency": "EUR",
  "availability": "in_stock",
  "extraction_status": "success",
  "source_url": "https://example.com/products/acme-mug-m-100",
  "observed_at": "2026-11-14T13:00:00Z",
  "matching_status": "needs_review",
  "extraction_error": null,
  "extracted_product": null
}
```

Examples here illustrate the JSON contract; they are not live observations.
Failed/non-product extractions are also saved, with null price and the real
extraction status. Unknown data is never manufactured. If an extracted price
cannot fit numeric(14,2) exactly, price is stored as null, status is partial, and
the response reports the reason. No silent rounding occurs.

The POST response wraps the observation:

```json
{
  "observation": { "...": "observation object shown above" },
  "change": {
    "status": "migration_required",
    "previous_observation_id": null,
    "price_difference": null,
    "percentage_change": null,
    "threshold_percent": "5",
    "exceeds_threshold": false
  },
  "alert": null,
  "alert_status": "migration_required",
  "replayed": false
}
```

HTTP 200 means the observation was saved or replayed; inspect
`observation.extraction_status` to determine whether scraping succeeded.
Database failure returns an error rather than pretending the observation was saved.
Inactive listings reject new observations with 409. History is append-only through
this backend; it exposes no observation update/delete routes.

## Existing-schema mode versus proposed migration

Default: `SUPABASE_PRICE_HISTORY_RPC_ENABLED=false`. This works with the supplied
four tables and does not create alerts. Existing tables cannot store identity
evidence, extraction-error details, or alert event keys. Accordingly:

- Basic observations are saved with all existing columns.
- `matching_status` defaults to `needs_review` in API responses; it is not stored.
- An extraction error is returned by the initial POST but cannot persist in
  history. Extracted identity snapshots are not persisted either.
- `change.status` and `alert_status` report `migration_required`.

Proposed file: `migrations/PROPOSED_price_history.sql`. **Do not apply without
approval and a check of the actual live schema.** It adds:

1. `matching_status`, `extraction_error`, and `extracted_product` to observations.
   The JSON snapshot preserves extracted name, brand, SKU, raw Decimal price,
   currency, status, and source. Old observations remain `needs_review`.
2. `source_observation_id` on alerts, an ownership foreign key, and a unique
   `(user_id, source_observation_id, event_type)` event constraint. Legacy alerts
   with null source IDs are preserved, not guessed or deduplicated retroactively.
3. An index for retrieving the latest valid confirmed observation.
4. `rivalsense_record_observation`, a SECURITY INVOKER function executable only
   by authenticated users. It locks the owned listing, checks the expected
   baseline, and commits the observation and optional alert in one transaction.
   Ownership filters and RLS remain active; no service-role credentials are used.

Only after the approved migration is applied and verified should
`SUPABASE_PRICE_HISTORY_RPC_ENABLED=true` be set and the backend restarted.
Missing RPC/columns cause a sanitized 503; no unsafe fallback enables alerts.
The proposed SQL was reviewed locally but has not run against PostgreSQL.

## Change detection after the approved migration

Set `PRICE_CHANGE_THRESHOLD_PERCENT=5` (default). Allowed range: 0–10000.
Threshold comparisons use Decimal cross-multiplication to avoid rounding at the
boundary. Money calculations use Decimal; displayed recurring percentages use
a 40-digit Decimal context. Upstream SDK/database numeric values are converted
with `Decimal(str(value))`; precision lost upstream cannot be recovered.

Only confirmed product identity plus a known price/currency is eligible. The
existing conservative identity rules are reused: exact normalized product name
plus explicit SKU/model/brand evidence; uncertain products require review.
The baseline is the latest valid confirmed observation of the same listing and
currency, skipping failed, unconfirmed, or missing-price records. No FX, tax,
shipping, or availability adjustment is applied.

`price_difference = new competitor price - previous competitor price`.
This differs from `/api/prices/compare`, whose difference is our price minus
the competitor price. Percentage change is signed; alert qualification uses its
absolute value and must **exceed**, not equal, the threshold.

Change statuses:

| Status | Meaning |
| --- | --- |
| `migration_required` | Existing-schema mode; confirmed history not available |
| `not_comparable` | Current or baseline identity/price/currency not valid |
| `no_baseline` | First valid observation; no alert |
| `zero_baseline` | Previous price was zero; percentage undefined, no alert |
| `unchanged` | Valid prices equal; no alert |
| `changed` | Valid price differs; inspect exceeds_threshold |
| `out_of_order` | Observation time is not later than the baseline; saved, no alert |
| `replayed` | Existing observation returned; change processing not repeated |

New qualifying changes create an unread, medium-severity
`competitor_price_change` alert. Alert responses contain `id`, `user_id`,
`product_id`, `event_type`, `severity`, `title`, `description`, `old_price`,
`new_price`, `currency`, `source_url`, `status`, and `created_at`.
`alert_status` is `created`, `not_triggered`, `not_reprocessed`, or
`migration_required`. A replay may omit the alert; `GET /api/alerts` is the
authoritative alert list.

Baseline contention causes up to three database-only recomputations with no
additional extraction. Continued contention returns 409; retry using the same
Idempotency-Key. The unique event constraint and transaction protect concurrent
backend recorders, not only sequential read-before-insert checks.

## Errors and testing

Errors use `{ "detail": "sanitized message" }`, except FastAPI validation errors
whose `detail` is an array. Status codes: 400 unsafe URL, 401 invalid/missing
Supabase token, 403 RLS/foreign-key denial, 404 missing/inaccessible resource,
409 duplicate/inactive/contention conflict, 422 invalid request, and 503
configuration/Auth/database/RPC unavailable. No credentials belong in JSON bodies.

Run offline checks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

All 61 tests passed, and pip reported no broken requirements. Tests use mocked
Auth/PostgREST HTTP responses and Context.dev services. They cover token
verification outcomes, token forwarding, user isolation, append/replay behavior,
Decimal thresholds, precision restrictions, and atomic RPC request serialization.
They do not establish live RLS correctness, execute the migration, or prove
transaction/concurrency behavior in PostgreSQL. Those require a separately
approved database verification step after reviewing the live schema.

References: [Supabase Auth user verification](https://supabase.com/docs/reference/python/auth-getuser),
[RLS](https://supabase.com/docs/guides/database/postgres/row-level-security),
[official PostgREST client](https://github.com/supabase/supabase-py/tree/main/src/postgrest).
