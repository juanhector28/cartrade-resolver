# Paste the Link: source-of-truth architecture

## Evidence from production (2026-10-10)

- Encuentra24 ID 32882910: displayed asking price USD 38,000, original struck-through USD 43,182.
- Supabase row 1364738: price USD 45,000, scraped 2026-08-24, updated 2026-09-22.
- Render returns HTTP 403 for this URL via both httpx and Chromium. It cannot assert a live price.
- The fallback record has no Atlas provenance metadata and is NOT a fresh observation.

## Contract

Input: URL -> canonical marketplace + source listing ID. Every observation must carry `source_kind`, `source_url`, `captured_at`, `access_status`, field-level provenance and errors.

Adapters are independently tested. A successful HTTP status alone is not a successful extraction: title, listing ID, price/currency and freshness must pass validation. Enforce strict no guessing: historical inventory can seed identity, pictures and metadata, but not a currently verified asking price. Current price requires a live or authorized observation of the **same ad** with a timestamp within 24 hours.

On-source-error fallback must be explicit, so frontends cannot silently use a historical price as live. Persist evidence and extraction receipts separate from consumer inventory records.

## Pipeline

1. Canonicalize URL and stable listing ID.
2. Read existing current observation (max TTL 24h) if verified for same ID.
3. Route through registered source adapter with bounded timeouts, access-policy checks and origin-aware concurrency.
4. Prefer official / licensed feeds where available. No unauthorized access bypass.
5. Extract structured listing payload with field-level evidence, capture timestamp and original/crossed-out/current price semantics.
6. Validate invariants, persist immutable observation + receipt, update latest trustworthy serving state.
7. Return verified current fields; indicate blocked/unavailable fields explicitly. No product-facing manual-entry workaround.
8. Observe source-specific coverage, success rate, 403 frequency, price correctness, age, p50/p95 latency and failed IDs. Quarantine bad adapters instead of publishing wrong values.

## Launch gates

- For a pilot source, at least 30 distinct listing IDs and at least 10 discounted ads tested against the seller-visible page or official feed.
- Price correctness >= 99% of *successfully extracted* cases, 0 known mismatched IDs, no historical price marked live.
- Track *coverage* separately from *accuracy*: a source with blocked access may have 100% correctness over zero results, but must not pass readiness.
- Measure p95 latency and timeouts before opening to volume.
- Confirm rights/access terms for data ingestion, and document provider contracts.
- Run smoke tests after production deploy with several newly created ads, not just historical Atlas rows.

## Current limit

The evidence gate added in this PR is a *foundation*, not wired into the live endpoint yet. Connecting it without a working authorized acquisition path would only produce another dash for the Jeep. Do not merge this PR expecting to fix HTTP 403. First establish source access and demonstrate a real successful live observation.
