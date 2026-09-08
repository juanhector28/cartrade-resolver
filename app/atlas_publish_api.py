from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from .atlas_listing_validity import listing_validity
from .atlas_manifest_runner import _money_usd


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
        .select("id,url,status,source,raw_payload,is_addressable,updated_at,make,model,year,price_usd")
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
        .select("id,url,status,source,raw_payload,is_addressable,updated_at,make,model,year,price_usd")
        .eq("id", row_id)
        .limit(1)
        .execute().data or []
    )
    return rows[0] if rows else None


def _validity_payload(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result = listing_validity(rows)
    valid_rows = list(result.pop("valid_rows"))
    return result, valid_rows


def _inject_test_publish_collision(
    supabase: Any,
    *,
    source_id: str,
    manifest_version: int,
    candidates: list[dict[str, Any]],
) -> None:
    """Deterministic race used only by the isolated Factory harness."""
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



class AtlasShadowImportRequest(BaseModel):
    source_id: str = Field(min_length=3, max_length=240)
    manifest_version: int = Field(ge=1, le=1_000_000)
    country: str = Field(min_length=2, max_length=2)
    domain: str = Field(min_length=3, max_length=240)
    min_listings: int = Field(default=10, ge=1, le=100)
    items: list[dict[str, Any]] = Field(min_length=1, max_length=100)


def _shadow_import_record(
    *,
    source_id: str,
    manifest_version: int,
    country: str,
    domain: str,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    url = str(item.get("url") or item.get("source_url") or item.get("listing_url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None

    photos = item.get("photos") or []
    if isinstance(photos, str):
        photos = [photos]
    photos = [p for p in photos if isinstance(p, str) and p.startswith(("http://", "https://"))][:12]

    currency = str(item.get("currency") or "USD").upper()
    raw_price = item.get("price_usd")
    if raw_price in (None, ""):
        raw_price = item.get("price")
    price_usd = _money_usd(raw_price, currency)

    km = item.get("km")
    if km in (None, ""):
        km = item.get("mileage")
    if km in (None, ""):
        km = item.get("kilometers")

    raw = {k: v for k, v in item.items() if not str(k).startswith("_")}
    raw["atlas"] = {
        "source_id": source_id,
        "manifest_version": int(manifest_version),
        "shadow": True,
        "extractor": str(item.get("_atlas_extractor") or raw.get("extractor") or "structured_import"),
        "raw_price": raw_price,
        "raw_currency": currency,
    }
    now = _now_iso()
    return {
        "source": f"atlas:{domain}",
        "country": country.lower(),
        "url": url,
        "title": item.get("title") or item.get("name"),
        "make": item.get("make"),
        "model": item.get("model"),
        "year": item.get("year"),
        "km": km,
        "price_usd": price_usd,
        "currency": "USD" if price_usd is not None else currency,
        "fuel_type": item.get("fuel_type"),
        "transmission": item.get("transmission"),
        "location": item.get("location"),
        "photos": photos,
        "photo_count": len(photos),
        "primary_photo": photos[0] if photos else None,
        "raw_payload": raw,
        "scraped_at": now,
        "updated_at": now,
        "last_seen_at": now,
        "status": "atlas_shadow",
        "listing_state": "indexed",
    }


def _existing_by_url(supabase: Any, url: str) -> dict[str, Any] | None:
    rows = (
        supabase.table("scraped_listings")
        .select("id,url,status,source,raw_payload,is_addressable,updated_at")
        .eq("url", url)
        .limit(1)
        .execute().data or []
    )
    return rows[0] if rows else None


def import_shadow_items(
    supabase: Any,
    body: AtlasShadowImportRequest,
) -> dict[str, Any]:
    """Persist pre-extracted Atlas rows into shared non-addressable shadow inventory.

    This endpoint does not publish or activate anything. It only closes the
    storage gap between an already-extracted Atlas cache and Resolver's shared
    atlas_shadow plane. Publisher remains the sole staging/addressability gate.
    """
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not connected")

    source_id = body.source_id.strip()
    country = body.country.strip().upper()
    domain = body.domain.strip().lower().removeprefix("www.")
    manifest_version = int(body.manifest_version)

    if len(country) != 2 or source_id.split("-", 1)[0].lower() != country.lower():
        raise HTTPException(status_code=422, detail="source_id/country mismatch")
    if not domain or "." not in domain:
        raise HTTPException(status_code=422, detail="valid domain is required")

    records = [
        row for row in (
            _shadow_import_record(
                source_id=source_id,
                manifest_version=manifest_version,
                country=country,
                domain=domain,
                item=item,
            )
            for item in body.items
            if isinstance(item, dict)
        )
        if row is not None
    ]
    validity = listing_validity(records)
    valid_records = list(validity.pop("valid_rows"))

    if not validity["passes_threshold"] or validity["valid_count"] < int(body.min_listings):
        return {
            "result": "rejected_precondition",
            "reason": (
                "core_listing_coverage_below_80"
                if not validity["passes_threshold"]
                else "insufficient_valid_import_inventory"
            ),
            "source_id": source_id,
            "manifest_version": manifest_version,
            "input_count": len(body.items),
            "normalized_count": len(records),
            "min_listings": int(body.min_listings),
            **validity,
            "saved_shadow": 0,
            "refreshed_shadow": 0,
            "protected_collision_count": 0,
            "protected_collision_urls": [],
        }

    saved = 0
    refreshed = 0
    collisions: list[dict[str, Any]] = []
    errors: list[str] = []

    for record in valid_records:
        url = str(record.get("url") or "")
        try:
            existing = _existing_by_url(supabase, url)
            if existing:
                meta = _atlas_meta(existing)
                same_shadow_source = bool(
                    existing.get("status") == "atlas_shadow"
                    and meta.get("source_id") == source_id
                )
                if not same_shadow_source:
                    collisions.append({
                        "url": url,
                        "reason": "shadow_collision_existing_owner",
                        "existing_status": existing.get("status"),
                        "existing_source": existing.get("source"),
                        "existing_source_id": meta.get("source_id"),
                        "existing_manifest_version": meta.get("manifest_version"),
                    })
                    continue
                response = (
                    supabase.table("scraped_listings")
                    .update(record)
                    .eq("id", existing["id"])
                    .eq("status", "atlas_shadow")
                    .contains("raw_payload", {"atlas": {"source_id": source_id}})
                    .execute()
                )
                if response.data:
                    refreshed += len(response.data)
                else:
                    collisions.append({"url": url, "reason": "conditional_shadow_refresh_lost_race"})
                continue

            try:
                response = supabase.table("scraped_listings").insert(record).execute()
            except Exception:
                current = _existing_by_url(supabase, url)
                meta = _atlas_meta(current)
                collisions.append({
                    "url": url,
                    "reason": "shadow_insert_collision",
                    "existing_status": (current or {}).get("status"),
                    "existing_source_id": meta.get("source_id"),
                    "existing_manifest_version": meta.get("manifest_version"),
                })
                continue
            if response.data:
                saved += len(response.data)
        except Exception as exc:
            errors.append(str(exc)[:300])

    final_rows = _exact_rows(
        supabase,
        status="atlas_shadow",
        source_id=source_id,
        manifest_version=manifest_version,
    )
    final_validity, valid_final = _validity_payload(final_rows)
    ready = bool(final_validity["passes_threshold"] and len(valid_final) >= int(body.min_listings))

    return {
        "result": "imported" if ready else "insufficient_after_collisions",
        "source_id": source_id,
        "manifest_version": manifest_version,
        "input_count": len(body.items),
        "normalized_count": len(records),
        "min_listings": int(body.min_listings),
        **validity,
        "saved_shadow": saved,
        "refreshed_shadow": refreshed,
        "protected_collision_count": len(collisions),
        "protected_collision_urls": [str(row.get("url") or "") for row in collisions[:100]],
        "protected_collisions": collisions[:100],
        "save_errors": errors[:50],
        "final_shadow_count": len(final_rows),
        "final_valid_shadow_count": len(valid_final),
        "final_valid_listing_coverage_pct": final_validity["valid_coverage_pct"],
        "addressable": False,
    }

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

    exact_rows = candidates + existing_addressable
    exact_validity, _ = _validity_payload(exact_rows)
    candidate_validity, valid_candidates = _validity_payload(candidates)
    existing_validity, valid_existing = _validity_payload(existing_addressable)

    ready = bool(
        exact_validity["passes_threshold"]
        and exact_validity["valid_count"] >= body.min_listings
    )
    common = {
        "source_id": source_id,
        "manifest_version": manifest_version,
        "idempotency_key": body.idempotency_key,
        "started_at": started_at,
        "shadow_candidate_count": len(candidates),
        "valid_shadow_candidate_count": candidate_validity["valid_count"],
        "existing_addressable_count": len(existing_addressable),
        "valid_existing_addressable_count": existing_validity["valid_count"],
        "valid_listing_count": exact_validity["valid_count"],
        "valid_listing_coverage_pct": exact_validity["valid_coverage_pct"],
        "valid_listing_threshold_pct": exact_validity["threshold_pct"],
        "min_listings": body.min_listings,
    }

    if not ready:
        reason = (
            "core_listing_coverage_below_80"
            if not exact_validity["passes_threshold"]
            else "insufficient_valid_exact_inventory"
        )
        return {
            **common,
            "result": "rejected_precondition",
            "reason": reason,
            "completed_at": _now_iso(),
            "final_addressable_count": len(valid_existing),
            "promoted_count": 0,
            "protected_collision_count": 0,
            "protected_collision_urls": [],
            "dry_run": body.dry_run,
        }

    if body.dry_run:
        return {
            **common,
            "result": "ready",
            "completed_at": _now_iso(),
            "final_addressable_count": len(valid_existing),
            "promoted_count": 0,
            "protected_collision_count": 0,
            "protected_collision_urls": [],
            "dry_run": True,
        }

    # Snapshot is fixed above. Any ownership/status change from this point is a
    # publish collision and must fail closed for that URL. Invalid rows are never
    # promoted, even when source-level coverage remains above the 80% gate.
    _inject_test_publish_collision(
        supabase,
        source_id=source_id,
        manifest_version=manifest_version,
        candidates=valid_candidates,
    )

    promoted = 0
    collisions: list[dict[str, Any]] = []
    now = _now_iso()
    for candidate in valid_candidates:
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
    final_validity, valid_final = _validity_payload(final_addressable)
    result = (
        "published"
        if final_validity["passes_threshold"] and len(valid_final) >= body.min_listings
        else "insufficient_after_collisions"
    )
    collision_urls = [str(item.get("url") or "") for item in collisions if item.get("url")]

    return {
        **common,
        "result": result,
        "completed_at": _now_iso(),
        "promoted_count": promoted,
        "protected_collision_count": len(collisions),
        "protected_collision_urls": collision_urls[:100],
        "protected_collisions": collisions[:100],
        "final_addressable_count": len(valid_final),
        "final_valid_listing_coverage_pct": final_validity["valid_coverage_pct"],
        "dry_run": False,
    }


def install(app: Any, supabase: Any) -> None:
    @app.post("/atlas/import-shadow")
    def atlas_import_shadow(
        body: AtlasShadowImportRequest,
        x_atlas_token: str | None = Header(default=None),
    ):
        _require_publish_token(x_atlas_token)
        return import_shadow_items(supabase, body)

    @app.post("/atlas/publish-source")
    def atlas_publish_source(
        body: AtlasPublishRequest,
        x_atlas_token: str | None = Header(default=None),
    ):
        _require_publish_token(x_atlas_token)
        return publish_source(supabase, body)
