# Atlas Publisher ↔ Resolver Contract v2

Status: frozen for Factory certification.

## Request

`POST /atlas/publish-source`

Fields:
- `source_id`: exact Atlas source id.
- `manifest_version`: exact registry manifest identity.
- `idempotency_key`: must equal `publish:{source_id}:{manifest_version}`.
- `min_listings`: minimum valid exact inventory required.
- `dry_run`: `true` for immutable readiness/snapshot inspection, `false` for publish.
- `expected_snapshot_hash`: required for every v2 mutating publish. It must equal the `candidate_snapshot_hash` returned by the immediately preceding dry-run for the same exact identity.

## Response contract

Every response carries `contract_version=2`.

A successful dry-run with `result=ready` MUST contain:
- `candidate_snapshot_hash`: SHA-256 over the deterministic ordered semantic snapshot.
- `semantic_assertion_complete=true`.
- `semantic_assertion_rows`: exactly `valid_listing_count` rows.
- Each semantic row contains `id`, `url`, `make`, `model`, `year`, `price_usd`.
- `valid_listing_count`, `valid_listing_coverage_pct`, and `valid_listing_threshold_pct` are computed by the Resolver canonical listing-validity contract.

The snapshot is built from the same exact source/manifest rows used to decide readiness. Invalid canonical rows are not included in `semantic_assertion_rows`.

## Mutation rule

A v2 non-dry-run request MUST fail closed when:
- `expected_snapshot_hash` is missing, or
- `expected_snapshot_hash != candidate_snapshot_hash` recomputed immediately before mutation.

A successful publish therefore proves that semantic assertion and mutation refer to the same exact inventory snapshot.

## Ownership

The Resolver owns canonical listing validity and snapshot construction. Atlas Promotion and Publisher must consume this contract rather than duplicate canonical validity rules.

## Certification rule

Publisher certification is incomplete unless a live cross-service probe against the deployed Resolver validates this contract. A mocked Resolver response cannot produce a production Publisher PASS.