from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from .atlas_canonical_verifier import CanonicalVerifyRequest, verify_and_write
from .atlas_publish_api import AtlasPublishRequest, publish_source
from .atlas_source_registry import list_sources, put_source, resolve_source

_REFRESH_RUNNING: set[str] = set()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _atlas_meta(row: dict[str, Any] | None) -> dict[str, Any]:
    raw = (row or {}).get("raw_payload")
    atlas = raw.get("atlas") if isinstance(raw, dict) else None
    return atlas if isinstance(atlas, dict) else {}


def _exact_staging_rows(supabase: Any, source_id: str, manifest_version: int) -> list[dict[str, Any]]:
    rows = (
        supabase.table("scraped_listings")
        .select("id,url,status,listing_state,is_addressable,last_seen_at,updated_at,raw_payload")
        .eq("status", "staging")
        .contains("raw_payload", {"atlas": {"source_id": source_id}})
        .limit(5000)
        .execute().data or []
    )
    return [
        dict(row) for row in rows
        if _atlas_meta(row).get("source_id") == source_id
        and int(_atlas_meta(row).get("manifest_version") or 0) == manifest_version
    ]


def source_snapshot(supabase: Any, source_id: str, manifest_version: int) -> dict[str, Any]:
    rows = _exact_staging_rows(supabase, source_id, manifest_version)
    clocks = [str(row.get("last_seen_at")) for row in rows if row.get("last_seen_at")]
    return {
        "count": len(rows),
        "addressable_count": sum(1 for row in rows if row.get("is_addressable") is True),
        "oldest_last_seen_at": min(clocks) if clocks else None,
        "newest_last_seen_at": max(clocks) if clocks else None,
    }


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def source_is_due(snapshot: dict[str, Any], cadence_seconds: int, *, now: datetime | None = None) -> bool:
    oldest = _parse_dt(snapshot.get("oldest_last_seen_at"))
    if oldest is None:
        return True
    return oldest <= (now or _now()) - timedelta(seconds=max(300, int(cadence_seconds)))


def _observed_urls(run_result: dict[str, Any]) -> set[str]:
    raw = run_result.get("observed_urls")
    if isinstance(raw, list):
        return {str(url).strip() for url in raw if str(url).strip()}
    sample = run_result.get("sample")
    if isinstance(sample, list):
        return {str(row.get("url") or "").strip() for row in sample if isinstance(row, dict) and row.get("url")}
    return set()


def _refresh_observed_existing(
    supabase: Any,
    *,
    source_id: str,
    manifest_version: int,
    observed_urls: set[str],
) -> int:
    if not observed_urls:
        return 0
    now = _now_iso()
    touched = 0
    for row in _exact_staging_rows(supabase, source_id, manifest_version):
        url = str(row.get("url") or "")
        if url not in observed_urls:
            continue
        response = (
            supabase.table("scraped_listings")
            .update({"last_seen_at": now, "updated_at": now})
            .eq("id", row["id"])
            .eq("status", "staging")
            .contains("raw_payload", {"atlas": {"source_id": source_id, "manifest_version": manifest_version}})
            .execute()
        )
        if response.data:
            touched += len(response.data)
    return touched


def _retire_missing_existing(
    supabase: Any,
    *,
    source_id: str,
    manifest_version: int,
    observed_urls: set[str],
) -> int:
    if not observed_urls:
        return 0
    retired = 0
    now = _now_iso()
    for row in _exact_staging_rows(supabase, source_id, manifest_version):
        url = str(row.get("url") or "")
        if not url or url in observed_urls:
            continue
        raw = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else {}
        raw = dict(raw)
        atlas = raw.get("atlas") if isinstance(raw.get("atlas"), dict) else {}
        atlas = dict(atlas)
        atlas["publish_rollback"] = {
            "reason": "not_observed_in_complete_refresh",
            "at": now,
            "source_id": source_id,
            "manifest_version": manifest_version,
        }
        raw["atlas"] = atlas
        response = (
            supabase.table("scraped_listings")
            .update({
                "status": "atlas_shadow",
                "listing_state": "expired",
                "raw_payload": raw,
                "updated_at": now,
            })
            .eq("id", row["id"])
            .eq("status", "staging")
            .contains("raw_payload", {"atlas": {"source_id": source_id, "manifest_version": manifest_version}})
            .execute()
        )
        if response.data:
            retired += len(response.data)
    return retired


def _record_publish_job(
    supabase: Any,
    *,
    source_id: str,
    manifest_version: int,
    request_payload: dict[str, Any],
    result: dict[str, Any],
) -> str:
    job_id = str(uuid.uuid4())
    now = _now_iso()
    row = {
        "job_id": job_id,
        "idempotency_key": f"refresh-publish:{source_id}:{manifest_version}:{job_id}",
        "operation": "publish_source",
        "source_id": source_id,
        "manifest_version": manifest_version,
        "state": "succeeded",
        "request": request_payload,
        "result": result,
        "error": None,
        "attempt_count": 1,
        "created_at": now,
        "started_at": now,
        "heartbeat_at": now,
        "completed_at": now,
        "updated_at": now,
    }
    supabase.table("atlas_runtime_jobs").insert(row).execute()
    return job_id


def _write_registry_outcome(supabase: Any, source: dict[str, Any], **updates: Any) -> None:
    if source.get("registry_backend") != "registry_private_config":
        return
    payload = {k: v for k, v in source.items() if not k.startswith("registry_")}
    payload.update(updates)
    put_source(supabase, payload)


async def refresh_source_once(
    supabase: Any,
    runner: Any,
    source_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    source_id = source_id.strip()
    source = resolve_source(supabase, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="atlas_source_not_registered")
    if not source.get("active", True):
        return {"source_id": source_id, "result": "skipped_inactive"}

    manifest = source.get("manifest")
    if not isinstance(manifest, dict) or not manifest:
        raise HTTPException(status_code=409, detail="atlas_source_manifest_missing")
    manifest_version = int(source.get("manifest_version") or 0)
    if manifest_version < 1:
        raise HTTPException(status_code=409, detail="atlas_manifest_version_invalid")

    before = source_snapshot(supabase, source_id, manifest_version)
    cadence_seconds = max(300, int(source.get("cadence_seconds") or 86400))
    if not force and not source_is_due(before, cadence_seconds):
        return {
            "source_id": source_id,
            "manifest_version": manifest_version,
            "result": "skipped_fresh",
            "before": before,
        }

    run_limit = 100
    scan_limit = min(300, max(run_limit, int(source.get("scan_limit") or 300)))
    _write_registry_outcome(
        supabase,
        source,
        last_refresh_started_at=_now_iso(),
        last_refresh_status="running",
    )

    try:
        run_result = await runner.run(
            source_id=source_id,
            country=str(source.get("country") or "").strip(),
            domain=str(source.get("domain") or "").strip(),
            manifest=manifest,
            manifest_version=manifest_version,
            limit=run_limit,
            scan_limit=scan_limit,
            persist=True,
        )
        quality = run_result.get("activation_quality") if isinstance(run_result.get("activation_quality"), dict) else {}
        if not run_result.get("ok"):
            raise RuntimeError(f"run_source_failed:{run_result}")
        if quality and not quality.get("eligible"):
            raise RuntimeError(f"activation_quality_failed:{quality}")

        observed = _observed_urls(run_result)
        touched = _refresh_observed_existing(
            supabase,
            source_id=source_id,
            manifest_version=manifest_version,
            observed_urls=observed,
        )

        full_observation = bool(
            observed
            and int(run_result.get("valid_listings") or 0) < run_limit
            and not (run_result.get("save_errors") or [])
        )
        retired = 0
        if full_observation:
            retired = _retire_missing_existing(
                supabase,
                source_id=source_id,
                manifest_version=manifest_version,
                observed_urls=observed,
            )

        natural_key = f"publish:{source_id}:{manifest_version}"
        min_listings = max(1, int(source.get("min_listings") or 10))
        dry_req = AtlasPublishRequest(
            source_id=source_id,
            manifest_version=manifest_version,
            idempotency_key=natural_key,
            min_listings=min_listings,
            dry_run=True,
        )
        dry = publish_source(supabase, dry_req)
        if dry.get("result") != "ready":
            raise RuntimeError(f"publish_dry_run_not_ready:{dry}")

        publish_req = AtlasPublishRequest(
            source_id=source_id,
            manifest_version=manifest_version,
            idempotency_key=natural_key,
            min_listings=min_listings,
            dry_run=False,
            expected_snapshot_hash=str(dry.get("candidate_snapshot_hash") or ""),
        )
        published = publish_source(supabase, publish_req)
        if published.get("result") != "published":
            raise RuntimeError(f"publish_failed:{published}")

        publish_job_id = _record_publish_job(
            supabase,
            source_id=source_id,
            manifest_version=manifest_version,
            request_payload=publish_req.model_dump(mode="json"),
            result=published,
        )
        expected_count = int(published.get("final_addressable_count") or 0)
        if expected_count < min_listings:
            raise RuntimeError("published_count_below_minimum")

        verification = verify_and_write(
            supabase,
            CanonicalVerifyRequest(
                source_id=source_id,
                manifest_version=manifest_version,
                expected_count=expected_count,
                mode="live_publish",
                publish_job_id=publish_job_id,
            ),
        )
        after = source_snapshot(supabase, source_id, manifest_version)
        result = {
            "source_id": source_id,
            "manifest_version": manifest_version,
            "result": "published",
            "registry_backend": source.get("registry_backend"),
            "before": before,
            "run": {
                "valid_listings": run_result.get("valid_listings"),
                "saved_shadow": run_result.get("saved_shadow"),
                "observed_count": len(observed),
                "full_observation": full_observation,
            },
            "reconciled": {"touched_existing": touched, "retired_missing": retired},
            "publish": {
                "final_addressable_count": expected_count,
                "promoted_count": published.get("promoted_count"),
                "publish_job_id": publish_job_id,
            },
            "canonical": {
                "verdict": verification.get("verdict"),
                "replayed": verification.get("replayed"),
                "receipt_id": (verification.get("receipt") or {}).get("id"),
            },
            "after": after,
            "completed_at": _now_iso(),
        }
        _write_registry_outcome(
            supabase,
            source,
            last_refresh_completed_at=result["completed_at"],
            last_refresh_status="published",
            last_refresh_receipt_id=result["canonical"]["receipt_id"],
            last_refresh_count=expected_count,
        )
        return result
    except Exception as exc:
        _write_registry_outcome(
            supabase,
            source,
            last_refresh_completed_at=_now_iso(),
            last_refresh_status="failed",
            last_refresh_error=str(exc)[:2000],
        )
        raise


class AtlasSourceRegistration(BaseModel):
    source_id: str = Field(min_length=3, max_length=240)
    country: str = Field(min_length=2, max_length=2)
    domain: str = Field(min_length=3, max_length=300)
    manifest_version: int = Field(ge=1, le=1_000_000)
    manifest: dict[str, Any]
    min_listings: int = Field(default=10, ge=1, le=5000)
    run_limit: int = Field(default=100, ge=1, le=100)
    scan_limit: int = Field(default=300, ge=1, le=300)
    cadence_seconds: int = Field(default=86400, ge=300, le=2_592_000)
    active: bool = True


class AtlasRefreshRequest(BaseModel):
    source_id: str = Field(min_length=3, max_length=240)
    force: bool = False


def install(app: Any, supabase: Any, runner: Any, require_token) -> None:
    @app.get("/atlas/registry/source/{source_id}")
    def atlas_registry_source(
        source_id: str,
        x_atlas_token: str | None = Header(default=None),
    ):
        require_token(x_atlas_token)
        source = resolve_source(supabase, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="atlas_source_not_registered")
        return source

    @app.post("/atlas/registry/source")
    def atlas_registry_source_put(
        body: AtlasSourceRegistration,
        x_atlas_token: str | None = Header(default=None),
    ):
        require_token(x_atlas_token)
        return put_source(supabase, body.model_dump(mode="json"))

    @app.post("/atlas/refresh/source")
    async def atlas_refresh_source(
        body: AtlasRefreshRequest,
        x_atlas_token: str | None = Header(default=None),
    ):
        require_token(x_atlas_token)
        if body.source_id in _REFRESH_RUNNING:
            raise HTTPException(status_code=409, detail="atlas_source_refresh_already_running")
        _REFRESH_RUNNING.add(body.source_id)
        try:
            return await refresh_source_once(supabase, runner, body.source_id, force=body.force)
        finally:
            _REFRESH_RUNNING.discard(body.source_id)

    if os.getenv("ATLAS_REFRESH_ORCHESTRATOR_ENABLED", "0") != "1":
        return

    poll_seconds = max(60, int(os.getenv("ATLAS_REFRESH_POLL_SECONDS", "300")))

    @app.on_event("startup")
    async def _atlas_refresh_scheduler_startup():
        async def loop():
            await asyncio.sleep(5)
            while True:
                try:
                    for source in list_sources(supabase):
                        source_id = str(source.get("source_id") or "")
                        if not source_id or not source.get("active", True) or source_id in _REFRESH_RUNNING:
                            continue
                        manifest_version = int(source.get("manifest_version") or 0)
                        if manifest_version < 1:
                            continue
                        snapshot = source_snapshot(supabase, source_id, manifest_version)
                        if not source_is_due(snapshot, int(source.get("cadence_seconds") or 86400)):
                            continue
                        _REFRESH_RUNNING.add(source_id)
                        try:
                            await refresh_source_once(supabase, runner, source_id, force=True)
                        except Exception as exc:
                            print("ATLAS_REFRESH_FAILED=" + str({"source_id": source_id, "error": str(exc)[:500]}), flush=True)
                        finally:
                            _REFRESH_RUNNING.discard(source_id)
                except Exception as exc:
                    print("ATLAS_REFRESH_SCHEDULER_ERROR=" + str(exc)[:500], flush=True)
                await asyncio.sleep(poll_seconds)

        asyncio.create_task(loop())
