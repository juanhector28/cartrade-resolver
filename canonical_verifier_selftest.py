from app.atlas_canonical_verifier import CanonicalVerifyRequest, evaluate_observation, validate_live_job

req = CanonicalVerifyRequest(source_id="gt-fixture", manifest_version=2, expected_count=20, publish_job_id="job-1")
base = {"operation": "publish_source", "source_id": "gt-fixture", "manifest_version": 2, "state": "succeeded", "result": {"result": "published", "dry_run": False, "final_addressable_count": 20}}

ready = {**base, "result": {**base["result"], "result": "ready"}}
assert validate_live_job(ready, req)["business_result_published"] is False
wrong_source = {**base, "source_id": "gt-other"}
assert validate_live_job(wrong_source, req)["job_source_match"] is False
wrong_manifest = {**base, "manifest_version": 3}
assert validate_live_job(wrong_manifest, req)["job_manifest_match"] is False

mismatch = evaluate_observation(publish_checks={"publish": True}, expected_count=20, staging_count=19, addressable_staging_count=19, served_count=19, exclusions=[], staging_urls=set(), served_urls=set())
assert mismatch["verdict"] == "FAIL" and "staging_count_exact" in mismatch["failed_checks"]

url = "https://fixture.invalid/excluded"
unreceipted = evaluate_observation(publish_checks={"publish": True}, expected_count=20, staging_count=20, addressable_staging_count=20, served_count=20, exclusions=[{"url": url, "receipt_id": ""}], staging_urls=set(), served_urls=set())
assert unreceipted["verdict"] == "FAIL"
present = evaluate_observation(publish_checks={"publish": True}, expected_count=20, staging_count=20, addressable_staging_count=20, served_count=20, exclusions=[{"url": url, "receipt_id": "r1"}], staging_urls={url}, served_urls={url})
assert present["verdict"] == "FAIL"

green = evaluate_observation(publish_checks={"publish": True}, expected_count=19, staging_count=19, addressable_staging_count=19, served_count=19, exclusions=[], staging_urls=set(), served_urls=set())
assert green["verdict"] == "PASS"
print("CANONICAL_VERIFIER_SELFTEST=PASS negative_controls=5 green_controls=1")
