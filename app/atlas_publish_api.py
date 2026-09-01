from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field


class AtlasPublishRequest(BaseModel):
    source_id: str = Field(min_length=3, max_length=240)
    manifest_version: int = Field(ge=1, le=1_000_000)
    idempotency_key: str = Field(min_length=8, max_length=500)
    min_listings: int = Field(default=10, ge=1, le=5000)
    dry_run: bool = False


def _now_iso() -> str:
    if os.getenv("ATLAS_TEST_ENV") == "1":
        try:
            from .test_clock import now_iso
            return now_iso()
        except Exception:
            pass
    return datetime.now(timezone.utc).isoformat()


def _require_publish_token(provided: str | None) -> None:
    expected = (
        os.environ.get("ATLAS_PUBLISH_TOKEN")
        or os.environ.get("ATLAS_BRIDGE_TOKEN")
        or os.environ.get("CRON_TOKEN")
    )
    if not expected:
        raise HTTPException(status_code=503, detail="Atlas publish token is not configured")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid atlas publish token")


def _atlas_meta(row: dict[str, Any] | None) -> dict[str, Any]:
    raw = (row or {}).get("raw_payload")
    if not isinstance(raw, dict):
        return {}
    atlas = raw.get("atlas")
    return atlas if isinstance(atlas, dict) else {}


def _exact_rows(
    supabase: Any,
    *,
    status: str,
    source_id: str,
    manifest_version: int,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    rows = (
        supabase.table("scraped_listings")
        .select("id,url,status,source,raw_payload,is_addressable,updated_at")
        .eq("status", status)
        .contains("raw_payload", {"atlas": {"source_id": source_id}})
        .limit(limit)
        .execute().data or []
    )
    return [
        row for row in rows
        if _atlas_meta(row).get("source_id") == source_id
        and _atlas_meta(row).get("manifest_version") == manifest_version
    ]


def _existing_by_id(supabase: Any, row_id: Any) -> dict[str, Any] | None:
    rows = (
        supabase.table("scraped_listings")
        .select("id,url,status,source,raw_payload,is_addressable,updated_at")
        .eq("id", row_id)
        .limit(1)
        .execute().data or []
    )
    return rows[0] if rows else None


def _inject_test_publish_collision(
    supabase: Any,
    *,
    source_id: str,
    manifest_version: int,
    candidates: list[dict[str, Any]],
) -> None:
    """Deterministic race used only by the isolated Factory harness.

    It simulates a manual/production row claiming one URL after Publisher has
    snapshotted trusted shadow inventory but before conditional promotion. The
    real publisher path must preserve that production row and report a protected
    collision rather than overwrite or duplicate it.
    """
    if os.getenv("ATLAS_TEST_ENV") != "1":
        return
    target = (os.getenv("ATLAS_TEST_PUBLISH_COLLISION_URL") or "").strip()
    if not target:
        return
    candidate = next((row for row in candidates if str(row.get("url") or "") == target), None)
    if not candidate:
        return
    current = _existing_by_id(supabase, candidate.get("id"))
    meta = _atlas_meta(current)
    if not current or current.get("status") != "atlas_shadow":
        return
    if meta.get("source_id") != source_id or meta.get("manifest_version") != manifest_version:
        return
    now = _now_iso()
    record = {
        "source": "manual-source",
        "title": "AtlasFixture GoldenDOM 2024 Publish Race Sentinel",
        "make": "AtlasFixture",
        "model": "GoldenDOM",
        "year": 2024,
        "km": 123456,
        "price_usd": 9999,
        "currency": "USD",
        "raw_payload": {"fixture": "publish-race-sentinel"},
        "status": "staging",
        "listing_state": "indexed",
        "updated_at": now,
        "last_seen_at": now,
    }
    (
        supabase.table("scraped_listings")
        .update(record)
        .eq("id", candidate["id"])
        .eq("status", "atlas_shadow")
        .contains(
            "raw_payload",
            {"atlas": {"source_id": source_id, "manifest_version": manifest_version}},
        )
        .execute()
    )


def publish_source(
    supabase: Any,
    body: AtlasPublishRequest,
) -> dict[str, Any]:
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not connected")

    source_id = body.source_id.strip()
    manifest_version = int(body.manifest_version)
    natural_key = f"publish:{source_id}:{manifest_version}"
    if body.idempotency_key != natural_key:
        return {
            "result": "rejected_precondition",
            "reason": "idempotency_key_must_match_natural_key",
            "source_id": source_id,
            "manifest_version": manifest_version,
            "idempotency_key": body.idempotency_key,
            "expected_idempotency_key": natural_key,
        }

    started_at = _now_iso()
    candidates = _exact_rows(
        supabase,
        status="atlas_shadow",
        source_id=source_id,
        manifest_version=manifest_version,
    )
    existing = _exact_rows(
        supabase,
        status="staging",
        source_id=source_id,
        manifest_version=manifest_version,
    )
    existing_addressable = [row for row in existing if row.get("is_addressable") is True]

    # A clean first publish requires at least min_listings trusted shadow rows.
    # An idempotent retry may have already promoted some rows, so combined exact
    # provenance can satisfy the precondition without re-creating inventory.
    exact_total = len(candidates) + len(existing_addressable)
    ready = bool(
        len(candidates) >= body.min_listings
        or (existing_addressable and exact_total >= body.min_listings)
    )
    if not ready:
        return {
            "result": "rejected_precondition",
            "reason": "insufficient_exact_shadow_inventory",
            "source_id": source_id,
            "manifest_version": manifest_version,
            "idempotency_key": body.idempotency_key,
            "started_at": started_at,
            "completed_at": _now_iso(),
            "shadow_candidate_count": len(candidates),
            "existing_addressable_count": len(existing_addressable),
            "final_addressable_count": len(existing_addressable),
            "promoted_count": 0,
            "protected_collision_count": 0,
            "protected_collision_urls": [],
            "min_listings": body.min_listings,
            "dry_run": body.dry_run,
        }

    if body.dry_run:
        return {
            "result": "ready",
            "source_id": source_id,
            "manifest_version": manifest_version,
            "idempotency_key": body.idempotency_key,
            "started_at": started_at,
            "completed_at": _now_iso(),
            "shadow_candidate_count": len(candidates),
            "existing_addressable_count": len(existing_addressable),
            "final_addressable_count": len(existing_addressable),
            "promoted_count": 0,
            "protected_collision_count": 0,
            "protected_collision_urls": [],
            "min_listings": body.min_listings,
            "dry_run": True,
        }

    # Snapshot is fixed above. Any ownership/status change from this point is a
    # publish collision and must fail closed for that URL.
    _inject_test_publish_collision(
        supabase,
        source_id=source_id,
        manifest_version=manifest_version,
        candidates=candidates,
    )

    promoted = 0
    collisions: list[dict[str, Any]] = []
    now = _now_iso()
    for candidate in candidates:
        current = _existing_by_id(supabase, candidate.get("id"))
        meta = _atlas_meta(current)
        if not current:
            collisions.append({"url": candidate.get("url"), "reason": "candidate_missing"})
            continue
        exact_owner = bool(
            current.get("status") == "atlas_shadow"
            and meta.get("source_id") == source_id
            and meta.get("manifest_version") == manifest_version
        )
        if not exact_owner:
            collisions.append(
                {
                    "url": candidate.get("url"),
                    "reason": "publish_collision_existing_production",
                    "existing_status": current.get("status"),
                    "existing_source": current.get("source"),
                    "existing_source_id": meta.get("source_id"),
                    "existing_manifest_version": meta.get("manifest_version"),
                }
            )
            continue

        response = (
            supabase.table("scraped_listings")
            .update({"status": "staging", "listing_state": "indexed", "updated_at": now})
            .eq("id", candidate["id"])
            .eq("status", "atlas_shadow")
            .contains(
                "raw_payload",
                {"atlas": {"source_id": source_id, "manifest_version": manifest_version}},
            )
            .execute()
        )
        if response.data:
            promoted += len(response.data)
        else:
            collisions.append(
                {
                    "url": candidate.get("url"),
                    "reason": "conditional_update_lost_race",
                }
            )

    final_rows = _exact_rows(
        supabase,
        status="staging",
        source_id=source_id,
        manifest_version=manifest_version,
    )
    final_addressable = [row for row in final_rows if row.get("is_addressable") is True]
    result = "published" if len(final_addressable) >= body.min_listings else "insufficient_after_collisions"
    collision_urls = [str(item.get("url") or "") for item in collisions if item.get("url")]

    return {
        "result": result,
        "source_id": source_id,
        "manifest_version": manifest_version,
        "idempotency_key": body.idempotency_key,
        "started_at": started_at,
        "completed_at": _now_iso(),
        "shadow_candidate_count": len(candidates),
        "existing_addressable_count": len(existing_addressable),
        "promoted_count": promoted,
        "protected_collision_count": len(collisions),
        "protected_collision_urls": collision_urls[:100],
        "protected_collisions": collisions[:100],
        "final_addressable_count": len(final_addressable),
        "min_listings": body.min_listings,
        "dry_run": False,
    }


def install(app: Any, supabase: Any) -> None:
    @app.post("/atlas/publish-source")
    def atlas_publish_source(
        body: AtlasPublishRequest,
        x_atlas_token: str | None = Header(default=None),
    ):
        _require_publish_token(x_atlas_token)
        return publish_source(supabase, body)
