# MarginGuard backend

FastAPI backend for RivalSense (originally MarginGuard), with Context.dev product
extraction. The original root and health routes are preserved. Supabase tracking
is available through the backend; no frontend is included.

Task 4 adds authenticated Supabase product tracking and append-only price history.
See [the API guide for Rebecca](docs/supabase-api.md) for configuration, requests,
responses, and migration limitations. Basic tracking supports the supplied
schema; confirmed change detection and atomic alerts require the separately
approved migration. No live schema change is performed by application startup.

The recording migration is under revision: see
[the security and idempotency review](docs/recording-migration-review.md).
The revised signed RPC requires durable backend capture receipts and new wiring;
do not enable the existing atomic-mode flag against that proposal.

## Run locally (PowerShell)

From the project folder, use the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Copy the environment file only if you do not already have a `.env` file.
The defaults also work without creating `.env`.

- API: http://127.0.0.1:8000/
- Health: http://127.0.0.1:8000/health
- Interactive API documentation: http://127.0.0.1:8000/docs

The health endpoint checks that the API is running. It does not check external services.
CORS allows `http://localhost:3000` and `http://localhost:5173` by default.
Set `CORS_ORIGINS` in `.env` to override the comma-separated list.

## Structure

```text
main.py                 Startup entry point
app/main.py             FastAPI application and CORS middleware
app/api/routes.py       Root and health endpoints
app/core/config.py      Environment loading and settings
```

`.venv` and `.env` are ignored by Git. Store future API keys in environment
variables or `.env`, never in source code.

## Extract a product

Set `CONTEXT_DEV_API_KEY` in your existing local `.env` file. Do not overwrite
that file or commit its contents. `.env.example` contains an empty placeholder.

Start the server with the command above, then use `/docs` or PowerShell:

```powershell
$body = @{ url = 'https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/prices/extract' -ContentType 'application/json' -Body $body
```

`POST /api/prices/extract` accepts `{ "url": "https://..." }` and returns:

```json
{
  "status": "partial",
  "product_name": "Example product",
  "brand": null,
  "price": 19.99,
  "currency": "EUR",
  "availability": "in_stock",
  "source_url": "https://example.com/product",
  "observed_at": "2026-11-14T12:00:00Z",
  "error": null
}
```

This example illustrates the response shape, not a live observation. Unknown
fields stay `null`. `success` means all five product fields are present and the
provider did not mark the response partial. `partial` means some usable product
fields were extracted but others are missing, or the provider marked it partial.
The UTC timestamp records when this backend received the observation.

| HTTP status | Meaning |
| --- | --- |
| 200 | Successful or partial extraction; inspect `status`. |
| 400 | Unsafe destination or redirect. |
| 422 | Invalid request (FastAPI `detail`) or non-product page (`status: failure`). |
| 502 | Retrieval, provider, or extraction failure; no usable product. |
| 503 | Missing key, provider authentication/permission problem, or rate limit. |
| 504 | Retrieval or extraction timed out. |

Extraction failures use the same product response shape, with null product
fields and a fixed `error` message. Raw provider exception messages and responses
are never forwarded. No results are stored.

## URL checks and service settings

Only HTTPS on port 443 without URL credentials is accepted. DNS answers must all
be public unicast addresses. Localhost, private, loopback, link-local, reserved,
and internal destinations are rejected. A streaming preflight checks up to five
redirects without downloading response bodies, validating each destination
before following it. Its connections are pinned to a checked IP while preserving
TLS certificate hostname verification. HTTP downgrades are rejected.

The SDK then scrapes the checked URL and its returned final URL is validated
again. **Boundary:** Context.dev runs a separate remote browser. DNS changes,
conditional redirects, intermediate browser navigations, and subresources in
that browser cannot be controlled by the local preflight or final-URL check.
These checks reject observable unsafe redirects; they are not a complete remote
browser SSRF guarantee. Strict remote enforcement needs provider-side network
controls. Context.dev documents redirect-aware access policies, but these require
organization enablement and are not silently created by this application.

The official `context.dev` SDK calls `POST /v1/web/scrape` with product output,
`max_age_ms=0`, image deduplication off, standard retention, and `max_retries=0`.
The SDK timeout is 60 seconds; the API deadline is 55 seconds with partial results
allowed, leaving time to return the response. The preliminary URL checks have a
separate 10-second HTTP timeout per request.

## Verification

Offline unit tests (no API credits or external requests):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

One opt-in live extraction, using `.env` and consuming API credits:

```powershell
.\.venv\Scripts\python.exe -m scripts.live_extract
```

The live command prints only the tested URL, HTTP status, and normalized product
response. It calls the same endpoint implementation as the frontend.

Verified on 2026-11-14: all 25 offline tests passed after the integration review.
The real installed 2.50.0 SDK is exercised through a mocked HTTP transport to
verify `client.web.scrape`, request serialization (`maxAgeMs`, `productParams`,
`timeoutOpts`), and parsing of `isPartial`, `isProductPage`, and product fields.
Tests also cover repeated application imports without duplicate operation IDs,
malformed provider output, and DNS changes between preflight redirect hops.
The existing router declarations are kept once in `app/main.py`; there is no
setup script that appends declarations on reruns. Normal imports reuse modules,
and reloading the application module creates a fresh FastAPI instance.

The earlier single live command returned
HTTP 200 for the Books to Scrape URL above: **A Light in the Attic**, price
**51.77 GBP**, availability **in_stock**, brand **null**, status **partial**.
Observation time: `2026-11-14T11:59:59.843708Z`. This is demo-site data, not a
current commercial offer. No additional live request was made to fill the brand.
The integration review did not make another live API request.

New modules: `app/api/prices.py` (route), `app/schemas/prices.py` (models),
`app/services/context_client.py` (SDK), and `app/services/url_safety.py` (URL checks).

Official references: [Python SDK](https://docs.context.dev/sdks/python),
[product output](https://docs.context.dev/scrape/product),
[scrape API](https://docs.context.dev/api-reference/web-scraping/scrape), and
[access policies](https://docs.context.dev/optimization/access-policies).

## Compare competitor prices

`POST /api/prices/compare` accepts 1–5 URLs:

```json
{
  "product_name": "Acme Mug M-100",
  "selling_price": "25.00",
  "currency": "EUR",
  "sku": "MUG-100",
  "model_number": "M-100",
  "brand": "Acme",
  "competitor_urls": ["https://example.com/products/mug"]
}
```

`sku`, `model_number`, and `brand` are optional. Use a decimal string for
`selling_price` to avoid rounding in the frontend. Prices must be finite and
nonnegative, with at most 20 digits and 6 decimal places. Currency is a
three-letter code normalized to uppercase; no exchange-rate conversion occurs.

The shared extraction workflow checks each URL independently, with the same
URL safety limitations documented above. Invalid/unsafe URLs and extraction
errors become individual failure results, leaving other results intact.
URLs are processed sequentially; a five-URL request can take several minutes
if providers are slow. Each successful scrape can consume Context.dev credits.
Tests mock all provider and target-page traffic.

Identity matching is deliberately conservative and deterministic:

- Names must match after Unicode, letter-case, and whitespace normalization.
  Punctuation, capacities, sizes, colors, and variant words are preserved.
- An exact name plus a matching supplied SKU, an explicit supplied model in the
  extracted name, or a matching supplied brand confirms the match.
- Name-only matches, missing supporting evidence, different names, and conflicting
  retailer SKUs require review. Retailers may use different SKU namespaces.
- Conflicting supplied and extracted brands are marked `mismatch`.
- Failed extractions have matching status `unavailable`.

These are evidence rules, not proof of semantic equivalence. The SDK exposes SKU
and brand but no separate model-number field; model evidence is checked only
against the extracted name, never guessed. Model prefixes do not confirm longer
identifiers. Only `confirmed` products with a known price and the same currency
are comparable. Availability is reported but does not filter comparisons; prices
are the reported page amounts, without tax, shipping, or unit adjustments.

Each `competitors` entry contains requested and final source URLs, observation
timestamp, extracted name/brand/SKU/price/currency/availability, extraction status,
HTTP status and sanitized error, matching status and reason, a `comparable` flag,
comparison reason, and `price_difference` (null when excluded).

`price_difference = selling_price - competitor_price`: positive means our price
is higher; negative means it is lower. All comparison arithmetic uses Decimal.
Money values in comparison responses are JSON strings. The SDK supplies numeric
prices as floats; `Decimal(str(value))` avoids introducing further binary-float
arithmetic but cannot recover precision already lost upstream. The existing
`/extract` response retains its numeric price format.

The response also includes `comparable_count`, `lowest_competitor_price` (null
when none qualify), all tied `lowest_competitor_source_urls`, and a UTC timestamp.
Aggregate `status` is `success` when every row is fully extracted and comparable,
`failure` when every extraction fails, and `partial` otherwise. A structurally
valid comparison request returns HTTP 200 even if its individual extractions
fail; invalid request structure returns HTTP 422.

Task 3 verification: all 42 offline tests passed. The suite covers comparison rules, Decimal
precision, lower-priced exclusions, partial failures, and existing endpoints.
No live Context.dev requests were made for Task 3.
