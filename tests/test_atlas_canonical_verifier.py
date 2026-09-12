from app.atlas_canonical_verifier import CanonicalVerifyRequest, evaluate_observation, validate_live_job


def request():
    return CanonicalVerifyRequest(source_id="gt-fixture", manifest_version=2, expected_count=20, publish_job_id="job-1")


def job(result="published", source="gt-fixture", manifest=2):
    return {"operation": "publish_source", "source_id": source, "manifest_version": manifest, "state": "succeeded", "result": {"result": result, "dry_run": False, "final_addressable_count": 20}}


def test_control_ready_is_not_published():
    checks = validate_live_job(job(result="ready"), request())
    assert checks["job_state_succeeded"] is True
    assert checks["business_result_published"] is False


def test_control_wrong_identity_fails():
    assert validate_live_job(job(source="gt-other"), request())["job_source_match"] is False
    assert validate_live_job(job(manifest=3), request())["job_manifest_match"] is False


def test_control_count_mismatch_fails():
    out = evaluate_observation(publish_checks={"publish": True}, expected_count=20, staging_count=19, addressable_staging_count=19, served_count=19, exclusions=[], staging_urls=set(), served_urls=set())
    assert out["verdict"] == "FAIL"
    assert "staging_count_exact" in out["failed_checks"]
    assert "served_count_exact" in out["failed_checks"]


def test_control_exclusion_must_be_receipted_and_absent():
    url = "https://fixture.invalid/excluded"
    missing = evaluate_observation(publish_checks={"publish": True}, expected_count=20, staging_count=20, addressable_staging_count=20, served_count=20, exclusions=[{"url": url, "receipt_id": ""}], staging_urls=set(), served_urls=set())
    present = evaluate_observation(publish_checks={"publish": True}, expected_count=20, staging_count=20, addressable_staging_count=20, served_count=20, exclusions=[{"url": url, "receipt_id": "receipt-1"}], staging_urls={url}, served_urls={url})
    assert missing["verdict"] == "FAIL"
    assert present["verdict"] == "FAIL"


def test_green_exact_observation_passes():
    out = evaluate_observation(publish_checks={"publish": True}, expected_count=19, staging_count=19, addressable_staging_count=19, served_count=19, exclusions=[], staging_urls=set(), served_urls=set())
    assert out["verdict"] == "PASS"
