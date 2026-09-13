from fastapi import HTTPException

import app.atlas_canonical_verifier as cv
from app.atlas_canonical_verifier import (
    CanonicalVerifyRequest,
    evaluate_observation,
    validate_live_job,
)


def red(name: str, condition: bool, detail: str) -> None:
    assert condition, f"negative control did not go red: {name}: {detail}"
    print(f"CANONICAL_VERIFIER_RED_CONTROL name={name} verdict=FAIL detail={detail}")


# Frozen live-publish fixture. A correct verifier must reject each mutation below.
req = CanonicalVerifyRequest(
    source_id="gt-fixture",
    manifest_version=2,
    expected_count=20,
    publish_job_id="job-1",
)
base_job = {
    "operation": "publish_source",
    "source_id": "gt-fixture",
    "manifest_version": 2,
    "state": "succeeded",
    "result": {
        "result": "published",
        "dry_run": False,
        "final_addressable_count": 20,
    },
}

# 1) Expected 20, observed fixture 19.
count_19 = evaluate_observation(
    publish_checks={"publish_evidence_valid": True},
    expected_count=20,
    staging_count=19,
    addressable_staging_count=19,
    served_count=19,
    exclusions=[],
    staging_urls=set(),
    served_urls=set(),
)
red(
    "count_19_of_20",
    count_19["verdict"] == "FAIL"
    and "staging_count_exact" in count_19["failed_checks"]
    and "addressable_staging_count_exact" in count_19["failed_checks"]
    and "served_count_exact" in count_19["failed_checks"],
    ",".join(count_19["failed_checks"]),
)

# 2) Publish job belongs to another source.
wrong_source = {**base_job, "source_id": "gt-other"}
source_checks = validate_live_job(wrong_source, req)
red(
    "wrong_source",
    source_checks["job_source_match"] is False,
    "job_source_match=false",
)

# 3) Publish job belongs to another manifest version.
wrong_manifest = {**base_job, "manifest_version": 3}
manifest_checks = validate_live_job(wrong_manifest, req)
red(
    "wrong_manifest",
    manifest_checks["job_manifest_match"] is False,
    "job_manifest_match=false",
)

# 4) Exclusion exists but has no durable exclusion receipt.
excluded_url = "https://fixture.invalid/excluded"
missing_exclusion_receipt = evaluate_observation(
    publish_checks={"publish_evidence_valid": True},
    expected_count=20,
    staging_count=20,
    addressable_staging_count=20,
    served_count=20,
    exclusions=[{"url": excluded_url, "receipt_id": ""}],
    staging_urls=set(),
    served_urls=set(),
)
red(
    "missing_exclusion_receipt",
    missing_exclusion_receipt["verdict"] == "FAIL"
    and "exclusion_receipts_valid" in missing_exclusion_receipt["failed_checks"],
    ",".join(missing_exclusion_receipt["failed_checks"]),
)

# 5) All evidence is green, but the canonical receipt write returns no row.
# The verifier must fail closed rather than report PASS without a durable receipt.
class _EmptyResult:
    data = []


class _FakeQuery:
    def __init__(self):
        self.insert_called = False

    def select(self, *args, **kwargs):
        return self

    def contains(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def insert(self, *args, **kwargs):
        self.insert_called = True
        return self

    def execute(self):
        return _EmptyResult()


class _FakeSupabase:
    def table(self, _name):
        return _FakeQuery()


historical_req = CanonicalVerifyRequest(
    source_id="gt-fixture",
    manifest_version=2,
    expected_count=20,
    mode="historical_recertification",
    prior_receipt_id=99,
    reclassify_prior=False,
)
prior_receipt = {
    "id": 99,
    "source_id": "gt-fixture",
    "country": "GT",
    "manifest_version": 2,
    "publish_result": "published",
    "required_count": 10,
    "exact_count": 12,
    "published_at": "2026-09-01T00:00:00+00:00",
    "platform_family": "atlas",
}
fake_rows = [
    {
        "id": i,
        "url": f"https://fixture.invalid/{i}",
        "status": "staging",
        "source": "atlas:fixture.invalid",
        "raw_payload": {"atlas": {"source_id": "gt-fixture", "manifest_version": 2}},
        "is_addressable": True,
        "listing_state": "indexed",
        "last_seen_at": "2099-01-01T00:00:00+00:00",
        "make": "Toyota",
        "model": "Corolla",
        "year": 2024,
        "price_usd": 20000 + i,
    }
    for i in range(20)
]

_original_receipt_by_id = cv._receipt_by_id
_original_exact_rows = cv._exact_rows
try:
    cv._receipt_by_id = lambda _supabase, _receipt_id: dict(prior_receipt)
    cv._exact_rows = lambda _supabase, _req, served: [dict(r) for r in fake_rows]
    try:
        cv.verify_and_write(_FakeSupabase(), historical_req)
        canonical_receipt_absent_failed_closed = False
        canonical_receipt_absent_detail = "unexpected PASS"
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        canonical_receipt_absent_failed_closed = (
            exc.status_code == 503
            and detail.get("verdict") == "FAIL"
            and "canonical_receipt_write_empty" in (detail.get("failed_checks") or [])
        )
        canonical_receipt_absent_detail = (
            f"http={exc.status_code} failed_checks={detail.get('failed_checks')}"
        )
finally:
    cv._receipt_by_id = _original_receipt_by_id
    cv._exact_rows = _original_exact_rows

red(
    "canonical_receipt_absent",
    canonical_receipt_absent_failed_closed,
    canonical_receipt_absent_detail,
)

# Green control: an exact 20/20 observation with no exclusions must pass.
green = evaluate_observation(
    publish_checks={"publish_evidence_valid": True},
    expected_count=20,
    staging_count=20,
    addressable_staging_count=20,
    served_count=20,
    exclusions=[],
    staging_urls=set(),
    served_urls=set(),
)
assert green["verdict"] == "PASS", green
print("CANONICAL_VERIFIER_GREEN_CONTROL name=exact_20_of_20 verdict=PASS")
print("CANONICAL_VERIFIER_RED_EXAM=PASS required_negative_controls=5 green_controls=1")
