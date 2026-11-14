# Revised recording proposal — not approved or applied

This document supersedes the migration/atomic-mode portions of supabase-api.md.
The current deployed backend contract is unchanged. The new attestation helper
is offline preparation only; it is not wired to recording or enabled by a flag.
Do not set SUPABASE_PRICE_HISTORY_RPC_ENABLED=true: the old RPC contract is
deliberately absent from the revised proposal and must not be deployed alongside it.

## Why the previous design was insufficient

A publishable key plus a user's JWT cannot identify a trusted backend. A
SECURITY INVOKER function has the same table privileges as that user; revoking
INSERT from the user also prevents the function inserting. Keeping INSERT lets
the frontend bypass the function. RLS alone isolates owners but does not certify
extraction provenance or product matching.

The revised proposal requires a server-only HMAC signing secret, provisioned
privately into the backend and a private database configuration row after approval.
No secret was generated, requested, logged, committed, or provisioned here.
Use a cryptographically random secret of at least 32 bytes; the code rejects
short strings but cannot itself prove entropy. Do not use a Supabase JWT secret,
publishable key, service-role key, or Context.dev API key as this secret.

## Idempotency and conflicting retries

The stable identifier is `(verified user ID, backend capture-event ID)`.
PostgreSQL allocates the observation row UUID. Client observation UUIDs do not
identify recording operations and are not accepted by the new RPC.

The backend must issue and durably retain a capture receipt before extraction,
associate it with the owned listing, and reuse its event ID and immutable result
for retries. The same captured result is signed and submitted again if the
database response is lost. It is not scraped again merely to reconstruct a retry.
This durable receipt/job workflow still needs backend wiring before rollout;
the existing Idempotency-Key endpoint does not yet implement it.

A listing lock plus unique `(user_id,capture_event_id)` constraint gives one
record per capture. A replay returns the existing record only when the stored
JSON payload equals the supplied signed payload. Changed price, listing,
timestamp, reference product, or evidence under that ID raises a conflict.
An alert additionally has unique `(user_id,source_observation_id,event_type)`.
Across different listings, the event uniqueness constraint still rejects reuse.

No system can infer whether two wholly new capture-event IDs mean retries or
two deliberate new observations. The capture receipt is therefore a required
part of the protocol, not an optional UUID convention. A new provider fetch is
a new event; price/time alone is not used to collapse legitimate history.
Guarantees cover committed records and alerts, not exactly-once external billing.

## Threshold and evidence enforcement

The caller cannot supply a threshold, baseline, or alert instruction. PostgreSQL
selects the latest valid confirmed same-currency baseline under the listing lock
and uses a private threshold (default 5 percent). Exact NUMERIC arithmetic checks:

`abs(new_price - old_price) * 100 > old_price * threshold_percent`

Exactly 5 percent does not alert; 5.01 percent does, in either direction. A zero
baseline, an out-of-order observation, a missing price, or unconfirmed evidence
does not alert. Python uses Decimal; database enforcement necessarily uses exact
PostgreSQL NUMERIC arithmetic as a second trust boundary. The database setting
is authoritative; the old environment-only threshold must not control the new RPC.

The backend signs exact UTF-8 JSON bytes with HMAC-SHA256. The payload binds user,
listing, capture ID, timestamp, extraction result, reference product, validation
version, decision, and supporting evidence. The helper calls the existing
identity validator, rather than accepting a frontend `confirmed` flag.
The RPC verifies the signature and auth.uid(), checks the owned listing and
current reference fields, and rejects missing/unsupported confirmation evidence.
Changed reference fields make a new event's evidence stale; exact previously
committed replays remain replays. Signature validation authenticates backend
attestation, not ground truth: a compromised backend signing key defeats this
trust boundary. Conservative identity matching limitations still apply.

## Least privilege and RLS

Direct INSERT/UPDATE/DELETE privileges on observations are revoked from clients.
Direct alert creation and content edits are revoked; authenticated users keep
SELECT and UPDATE(status) with their existing owner policies. Check additional
inherited and column-level grants in the real project before execution.

The new function is SECURITY DEFINER, owned by a dedicated NOLOGIN,
NOBYPASSRLS, non-table-owner role, never granted to client/authenticator roles.
That role gets only the required SELECT/INSERT rights and listing UPDATE for
row locking; its owner policies still use auth.uid(). It has no observation or
alert UPDATE/DELETE grants. It can read the private signing key and threshold
but cannot modify them. Its function uses a fixed pg_catalog search path and
schema-qualified relations/functions. PUBLIC and anon cannot execute it.

No service-role key is used. Products, listings, historical observations, and
old alerts are retained. New event metadata is nullable for legacy rows; legacy
observations remain unconfirmed and are not guessed into baselines. No
auth.users, OAuth, Google authentication, or session settings are changed.

## Mandatory pre-execution review

No live schema inspection or database request was performed in this revision,
because the instruction forbids live Supabase access. Before applying anything:

1. With separate read-only authorization, run migrations/inspect_schema.sql.
2. Review actual columns, constraints, RLS, grants (including column grants),
   role memberships, ownership, triggers, old RPCs, and pgcrypto's schema.
3. Verify administrative authority to create/assign the restricted function role.
   The migration intentionally fails if required extension placement or grants
   differ; do not loosen permissions to make it pass.
4. Revise against discrepancies, obtain execution approval, and provision the
   private secret through a secure process. The proposal's secret is NULL, so
   signed recording fails closed until provisioned.
5. Wire the receipt/signing contract, then run PostgreSQL integration tests under
   real authenticated roles before considering any alert enablement.

Offline tests include HMAC tampering, evidence matching, cross-user payload
changes, threshold boundaries, and a threaded replay/conflict model. The model
does not run PostgreSQL or prove locks/RLS. Real concurrent SQL transactions,
direct INSERT denial, unsigned RPC denial, role inheritance, rollback, and
cross-user policies require the separately approved database verification step.
