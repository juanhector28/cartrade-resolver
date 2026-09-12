from pathlib import Path

p = Path('/app/app/atlas_publish_api.py')
s = p.read_text(encoding='utf-8')
marker = '# ATLAS_PUBLISH_SCOPED_EXCLUSIONS_V25'

if marker not in s:
    field_anchor = '    expected_snapshot_hash: str | None = Field(default=None, min_length=16, max_length=128)\n'
    field_new = field_anchor + '    exclusion_receipts: list[dict[str, Any]] = Field(default_factory=list, max_length=100)\n'
    if field_anchor not in s:
        raise RuntimeError('v25 AtlasPublishRequest anchor missing')
    s = s.replace(field_anchor, field_new, 1)

    helper_anchor = '\n\ndef _now_iso() -> str:\n'
    helper = r'''


def _validate_exclusion_receipts(
    receipts: list[dict[str, Any]],
    *,
    source_id: str,
    manifest_version: int,
) -> dict[str, Any]:
    valid: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for idx, receipt in enumerate(receipts or []):
        if not isinstance(receipt, dict):
            errors.append({"index": idx, "reason": "receipt_not_object"})
            continue
        url = str(receipt.get("url") or "").strip()
        checks = {
            "scope": str(receipt.get("scope") or "") == "cert_manifest",
            "source": str(receipt.get("source_id") or "") == str(source_id),
            "manifest": int(receipt.get("manifest_version") or 0) == int(manifest_version),
            "receipt_id": bool(str(receipt.get("receipt_id") or "").strip()),
            "url": bool(url),
            "reason": bool(str(receipt.get("reason") or "").strip()),
            "evidence": isinstance(receipt.get("evidence"), dict) and bool(receipt.get("evidence")),
            "duplicate_url": url not in seen_urls,
        }
        if not all(checks.values()):
            errors.append({
                "index": idx,
                "url": url or None,
                "reason": "invalid_exclusion_receipt",
                "checks": checks,
            })
            continue
        seen_urls.add(url)
        valid.append(receipt)

    return {
        "ok": not errors,
        "receipts": valid,
        "urls": sorted(seen_urls),
        "errors": errors,
    }
'''
    if helper_anchor not in s:
        raise RuntimeError('v25 _now_iso anchor missing')
    s = s.replace(helper_anchor, helper + helper_anchor, 1)

    start_anchor = '''    started_at = _now_iso()
    raw_candidates = _exact_rows(
'''
    start_new = '''    started_at = _now_iso()
    exclusion_validation = _validate_exclusion_receipts(
        body.exclusion_receipts,
        source_id=source_id,
        manifest_version=manifest_version,
    )
    if not exclusion_validation["ok"]:
        return {
            "contract_version": ATLAS_PUBLISH_CONTRACT_VERSION,
            "result": "rejected_precondition",
            "reason": "invalid_exclusion_receipt",
            "source_id": source_id,
            "manifest_version": manifest_version,
            "idempotency_key": body.idempotency_key,
            "exclusion_receipt_errors": exclusion_validation["errors"],
            "completed_at": _now_iso(),
            "promoted_count": 0,
        }

    requested_exclusion_urls = set(exclusion_validation["urls"])
    raw_candidates = _exact_rows(
'''
    if start_anchor not in s:
        raise RuntimeError('v25 publish start anchor missing')
    s = s.replace(start_anchor, start_new, 1)

    candidate_anchor = '''    rollback_quarantined = [row for row in raw_candidates if _publish_rollback_quarantined(row)]
    candidates = [row for row in raw_candidates if not _publish_rollback_quarantined(row)]
'''
    candidate_new = '''    rollback_quarantined = [row for row in raw_candidates if _publish_rollback_quarantined(row)]
    candidate_pool = [row for row in raw_candidates if not _publish_rollback_quarantined(row)]
    candidate_pool_urls = {str(row.get("url") or "") for row in candidate_pool if row.get("url")}
    missing_exclusion_targets = sorted(requested_exclusion_urls - candidate_pool_urls)
    if missing_exclusion_targets:
        return {
            "contract_version": ATLAS_PUBLISH_CONTRACT_VERSION,
            "result": "rejected_precondition",
            "reason": "exclusion_target_not_current_shadow_candidate",
            "source_id": source_id,
            "manifest_version": manifest_version,
            "idempotency_key": body.idempotency_key,
            "missing_exclusion_urls": missing_exclusion_targets,
            "completed_at": _now_iso(),
            "promoted_count": 0,
        }
    excluded_candidates = [
        row for row in candidate_pool
        if str(row.get("url") or "") in requested_exclusion_urls
    ]
    candidates = [
        row for row in candidate_pool
        if str(row.get("url") or "") not in requested_exclusion_urls
    ]
'''
    if candidate_anchor not in s:
        raise RuntimeError('v25 candidate filter anchor missing')
    s = s.replace(candidate_anchor, candidate_new, 1)

    common_anchor = '''        "shadow_candidate_raw_count": len(raw_candidates),
        "publish_rollback_quarantined_count": len(rollback_quarantined),
        "shadow_candidate_count": len(candidates),
'''
    common_new = '''        "shadow_candidate_raw_count": len(raw_candidates),
        "publish_rollback_quarantined_count": len(rollback_quarantined),
        "exclusion_receipts_validated": True,
        "excluded_candidate_count": len(excluded_candidates),
        "excluded_urls": sorted(requested_exclusion_urls),
        "excluded_receipt_ids": sorted(
            str(row.get("receipt_id") or "")
            for row in exclusion_validation["receipts"]
        ),
        "shadow_candidate_count": len(candidates),
'''
    if common_anchor not in s:
        raise RuntimeError('v25 common receipt anchor missing')
    s = s.replace(common_anchor, common_new, 1)

    s += '\n' + marker + '\n'
    p.write_text(s, encoding='utf-8')

src = p.read_text(encoding='utf-8')
assert 'exclusion_receipts: list[dict[str, Any]]' in src
assert 'exclusion_target_not_current_shadow_candidate' in src
assert '"excluded_candidate_count": len(excluded_candidates)' in src
assert 'requested_exclusion_urls' in src

print('Installed Atlas publish scoped exclusion receipts v25')
