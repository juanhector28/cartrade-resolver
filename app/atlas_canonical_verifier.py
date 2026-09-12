from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from .atlas_freshness_api import freshness_cutoff_iso

VERIFIER_VERSION = "canonical-verifier-v1"


class CanonicalExclusion(BaseModel):
    url: str = Field(min_length=5, max_length=2000)
    receipt_id: str = Field(min_length=3, max_length=500)
    reason: str | None = Field(default=None, max_length=500)


class CanonicalVerifyRequest(BaseModel):
    source_id: str = Field(min_length=3, max_length=240)
    manifest_version: int = Field(ge=1, le=1_000_000)
    expected_count: int = Field(ge=1, le=5000)
    mode: Literal["live_publish", "historical_recertification"] = "live_publish"
    publish_job_id: str | None = Field(default=None, max_length=120)
    prior_receipt_id: int | None = Field(default=None, ge=1)
    exclusions: list[CanonicalExclusion] = Field(default_factory=list)
    reclassify_prior: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atlas_meta(row: dict[str, Any] | None) -> dict[str, Any]:
    raw = (row or {}).get("raw_payload")
    atlas = raw.get("atlas") if isinstance(raw, dict) else None
    return atlas if isinstance(atlas, dict) else {}


def validate_live_job(job: dict[str, Any] | None, req: CanonicalVerifyRequest) -> dict[str, bool]:
    result = (job or {}).get("result")
    result = result if isinstance(result, dict) else {}
    return {
        "job_exists": isinstance(job, dict),
        "job_operation_publish_source": isinstance(job, dict) and job.get("operation") == "publish_source",
        "job_state_succeeded": isinstance(job, dict) and job.get("state") == "succeeded",
        "job_source_match": isinstance(job, dict) and job.get("source_id") == req.source_id,
        "job_manifest_match": isinstance(job, dict) and int(job.get("manifest_version") or 0) == req.manifest_version,
        "business_result_published": result.get("result") == "published",
        "not_dry_run": result.get("dry_run") is False,
        "job_final_count_match": int(result.get("final_addressable_count") or 0) == req.expected_count,
    }


def validate_historical_receipt(receipt: dict[str, Any] | None, req: CanonicalVerifyRequest) -> dict[str, bool]:
    return {
        "prior_receipt_exists": isinstance(receipt, dict),
        "prior_source_match": isinstance(receipt, dict) and receipt.get("source_id") == req.source_id,
        "prior_manifest_match": isinstance(receipt, dict) and int(receipt.get("manifest_version") or 0) == req.manifest_version,
        "prior_publish_result_published": isinstance(receipt, dict) and receipt.get("publish_result") == "published",
    }


def evaluate_observation(*, publish_checks: dict[str, bool], expected_count: int,
                         staging_count: int, addressable_staging_count: int,
                         served_count: int, exclusions: list[dict[str, Any]],
                         staging_urls: set[str], served_urls: set[str]) -> dict[str, Any]:
    checks = {
        **{k: bool(v) for k, v in publish_checks.items()},
        "expected_count_positive": expected_count > 0,
        "staging_count_exact": staging_count == expected_count,
        "addressable_staging_count_exact": addressable_staging_count == expected_count,
        "served_count_exact": served_count == expected_count,
        "exclusion_receipts_valid": all(bool(x.get("url")) and bool(x.get("receipt_id")) for x in exclusions),
        "excluded_absent_staging": all(str(x.get("url")) not in staging_urls for x in exclusions),
        "excluded_absent_serving": all(str(x.get("url")) not in served_urls for x in exclusions),
    }
    failed = sorted(k for k, v in checks.items() if not v)
    return {"verdict": "PASS" if not failed else "FAIL", "checks": checks, "failed_checks": failed}


def _exact_rows(supabase: Any, req: CanonicalVerifyRequest, *, served: bool) -> list[dict[str, Any]]:
    q = (supabase.table("scraped_listings")
         .select("id,url,status,source,raw_payload,is_addressable,listing_state,last_seen_at,make,model,year,price_usd")
         .eq("status", "staging")
         .contains("raw_payload", {"atlas": {"source_id": req.source_id}}))
    if served:
        q = q.eq("is_addressable", True).eq("listing_state", "indexed").gte("last_seen_at", freshness_cutoff_iso())
    rows = q.limit(5000).execute().data or []
    return [dict(r) for r in rows if _atlas_meta(r).get("source_id") == req.source_id
            and int(_atlas_meta(r).get("manifest_version") or 0) == req.manifest_version]


def _job_by_id(supabase: Any, job_id: str) -> dict[str, Any] | None:
    rows = (supabase.table("atlas_runtime_jobs")
            .select("job_id,operation,source_id,manifest_version,state,result,error,created_at,completed_at")
            .eq("job_id", job_id).limit(1).execute().data or [])
    return dict(rows[0]) if rows else None


def _receipt_by_id(supabase: Any, receipt_id: int) -> dict[str, Any] | None:
    rows = (supabase.table("atlas_searchable_source_receipts").select("*")
            .eq("id", receipt_id).limit(1).execute().data or [])
    return dict(rows[0]) if rows else None


def _verification_key(req: CanonicalVerifyRequest) -> str:
    payload = {"version": VERIFIER_VERSION, **req.model_dump(mode="json")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_and_write(supabase: Any, req: CanonicalVerifyRequest) -> dict[str, Any]:
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not connected")

    if req.mode == "live_publish":
        if not req.publish_job_id:
            raise HTTPException(status_code=422, detail="publish_job_id_required")
        publish_evidence = _job_by_id(supabase, req.publish_job_id)
        publish_checks = validate_live_job(publish_evidence, req)
        published_at = (publish_evidence or {}).get("completed_at")
    else:
        if not req.prior_receipt_id:
            raise HTTPException(status_code=422, detail="prior_receipt_id_required")
        publish_evidence = _receipt_by_id(supabase, req.prior_receipt_id)
        publish_checks = validate_historical_receipt(publish_evidence, req)
        published_at = (publish_evidence or {}).get("published_at")

    staging_rows = _exact_rows(supabase, req, served=False)
    served_rows = _exact_rows(supabase, req, served=True)
    addressable_rows = [r for r in staging_rows if r.get("is_addressable") is True]
    staging_urls = {str(r.get("url")) for r in staging_rows if r.get("url")}
    served_urls = {str(r.get("url")) for r in served_rows if r.get("url")}
    exclusions = [x.model_dump(mode="json") for x in req.exclusions]

    evaluation = evaluate_observation(
        publish_checks=publish_checks, expected_count=req.expected_count,
        staging_count=len(staging_rows), addressable_staging_count=len(addressable_rows),
        served_count=len(served_rows), exclusions=exclusions,
        staging_urls=staging_urls, served_urls=served_urls,
    )
    observed_at = _now_iso()
    key = _verification_key(req)
    writer = {"service": "cartrade-resolver", "component": "atlas_canonical_verifier",
              "version": VERIFIER_VERSION,
              "git_sha": os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT_SHA") or os.getenv("COMMIT_SHA")}
    evidence = {
        "verification_key": key, "verifier_version": VERIFIER_VERSION, "writer": writer,
        "mode": req.mode, "source_id": req.source_id, "manifest_version": req.manifest_version,
        "expected_count": req.expected_count, "observed_at": observed_at,
        "publish_job_id": req.publish_job_id, "prior_receipt_id": req.prior_receipt_id,
        "publish_evidence": publish_evidence,
        "materialization": {"staging_count": len(staging_rows), "addressable_staging_count": len(addressable_rows)},
        "serving_audit": {"contract": "staging+addressable+indexed+fresh+source+manifest",
                          "served_count": len(served_rows), "freshness_cutoff": freshness_cutoff_iso()},
        "exclusions": exclusions, **evaluation,
    }
    if evaluation["verdict"] != "PASS":
        raise HTTPException(status_code=409, detail=evidence)

    existing = (supabase.table("atlas_searchable_source_receipts").select("*")
                .contains("evidence", {"verification_key": key})
                .eq("publish_result", "published").limit(1).execute().data or [])
    if existing:
        return {"verdict": "PASS", "replayed": True, "receipt": existing[0], "evidence": evidence}

    sample = served_rows[0] if served_rows else {}
    canonical = {
        "source_id": req.source_id, "country": "GT", "manifest_version": req.manifest_version,
        "publish_result": "published", "publish_receipt_key": f"canonical:{VERIFIER_VERSION}:{key}",
        "required_count": req.expected_count, "exact_count": len(served_rows), "carly_ok": True,
        "carly_status_code": 200, "sample_url": sample.get("url"), "sample_make": sample.get("make"),
        "sample_model": sample.get("model"), "sample_year": sample.get("year"),
        "published_at": published_at, "probed_at": observed_at,
        "evidence": {**evidence, "classification": "end_to_end_certified"}, "platform_family": "atlas",
    }
    rows_to_insert: list[dict[str, Any]] = []
    if req.mode == "historical_recertification" and req.reclassify_prior and req.prior_receipt_id:
        prior = publish_evidence or {}
        rows_to_insert.append({
            "source_id": req.source_id, "country": str(prior.get("country") or "GT"),
            "manifest_version": req.manifest_version, "publish_result": "reclassified",
            "publish_receipt_key": f"reclassify:{req.prior_receipt_id}:{key}",
            "required_count": int(prior.get("required_count") or 0), "exact_count": int(prior.get("exact_count") or 0),
            "carly_ok": False, "carly_status_code": prior.get("carly_status_code"),
            "sample_url": prior.get("sample_url"), "sample_make": prior.get("sample_make"),
            "sample_model": prior.get("sample_model"), "sample_year": prior.get("sample_year"),
            "published_at": prior.get("published_at"), "probed_at": observed_at,
            "evidence": {"receipt_kind": "append_only_reclassification",
                         "classification": "serving_presence_verified_cardinality_unverified",
                         "supersedes_receipt_id": req.prior_receipt_id,
                         "superseded_by_verification_key": key,
                         "reason": "legacy Carly probe capped at 12 and did not certify full cardinality",
                         "writer": writer},
            "platform_family": prior.get("platform_family") or "atlas",
        })
    rows_to_insert.append(canonical)
    try:
        inserted = supabase.table("atlas_searchable_source_receipts").insert(rows_to_insert).execute().data or []
    except Exception as exc:
        raise HTTPException(status_code=503, detail={**evidence, "verdict": "FAIL",
                            "failed_checks": ["canonical_receipt_write"],
                            "write_error": f"{type(exc).__name__}: {str(exc)[:500]}"})
    if not inserted:
        raise HTTPException(status_code=503, detail={**evidence, "verdict": "FAIL",
                            "failed_checks": ["canonical_receipt_write_empty"]})
    return {"verdict": "PASS", "replayed": False, "receipt": inserted[-1],
            "reclassification_written": len(rows_to_insert) == 2, "evidence": evidence}


def install(app: Any, supabase: Any, require_token) -> None:
    @app.post("/atlas/canonical-verify")
    def atlas_canonical_verify(body: CanonicalVerifyRequest,
                               x_atlas_token: str | None = Header(default=None)):
        require_token(x_atlas_token)
        return verify_and_write(supabase, body)
