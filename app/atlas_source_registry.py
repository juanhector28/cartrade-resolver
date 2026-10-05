from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

REGISTRY_TABLE = "registry_private_config"
REGISTRY_PREFIX = "atlas_source_registry:"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(source_id: str) -> str:
    return f"{REGISTRY_PREFIX}{source_id.strip()}"


def _decode(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        decoded = json.loads(value)
    except Exception:
        return None
    return dict(decoded) if isinstance(decoded, dict) else None


def get_source(supabase: Any, source_id: str) -> dict[str, Any] | None:
    source_id = source_id.strip()
    rows = (
        supabase.table(REGISTRY_TABLE)
        .select("name,value,updated_at")
        .eq("name", _key(source_id))
        .limit(1)
        .execute().data or []
    )
    if rows:
        payload = _decode(rows[0].get("value"))
        if payload:
            payload["registry_backend"] = REGISTRY_TABLE
            payload["registry_updated_at"] = rows[0].get("updated_at")
            return payload
    return None


def latest_runtime_manifest(supabase: Any, source_id: str) -> dict[str, Any] | None:
    rows = (
        supabase.table("atlas_runtime_jobs")
        .select("source_id,manifest_version,request,completed_at")
        .eq("operation", "run_source")
        .eq("source_id", source_id.strip())
        .eq("state", "succeeded")
        .order("created_at", desc=True)
        .limit(1)
        .execute().data or []
    )
    if not rows:
        return None
    row = dict(rows[0])
    request = row.get("request") if isinstance(row.get("request"), dict) else {}
    manifest = request.get("manifest") if isinstance(request.get("manifest"), dict) else None
    if not manifest:
        return None
    country = str(request.get("country") or manifest.get("country") or "").strip().lower()
    domain = str(request.get("domain") or "").strip().lower()
    return {
        "source_id": source_id.strip(),
        "country": country,
        "domain": domain,
        "manifest_version": int(row.get("manifest_version") or request.get("manifest_version") or 0),
        "manifest": manifest,
        "min_listings": 10,
        "run_limit": max(20, int(request.get("limit") or 20)),
        "scan_limit": max(80, int(request.get("scan_limit") or 80)),
        "cadence_seconds": 86400,
        "active": True,
        "registry_backend": "atlas_runtime_jobs_fallback",
        "registry_updated_at": row.get("completed_at"),
    }


def resolve_source(supabase: Any, source_id: str) -> dict[str, Any] | None:
    return get_source(supabase, source_id) or latest_runtime_manifest(supabase, source_id)


def put_source(supabase: Any, payload: dict[str, Any]) -> dict[str, Any]:
    source_id = str(payload.get("source_id") or "").strip()
    if not source_id:
        raise ValueError("source_id_required")
    record = dict(payload)
    record["source_id"] = source_id
    record["country"] = str(record.get("country") or "").strip().lower()
    record["manifest_version"] = int(record.get("manifest_version") or 0)
    record["min_listings"] = max(1, int(record.get("min_listings") or 10))
    record["run_limit"] = min(100, max(record["min_listings"], int(record.get("run_limit") or 100)))
    record["scan_limit"] = min(300, max(record["run_limit"], int(record.get("scan_limit") or 300)))
    record["cadence_seconds"] = max(300, int(record.get("cadence_seconds") or 86400))
    record["active"] = bool(record.get("active", True))
    record["updated_at"] = _now_iso()
    (
        supabase.table(REGISTRY_TABLE)
        .upsert({
            "name": _key(source_id),
            "value": json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str),
            "updated_at": record["updated_at"],
        }, on_conflict="name")
        .execute()
    )
    record["registry_backend"] = REGISTRY_TABLE
    record["registry_updated_at"] = record["updated_at"]
    return record


def list_sources(supabase: Any) -> list[dict[str, Any]]:
    """List explicit registry sources plus recoverable published Atlas sources.

    A source that has already passed canonical publication must never disappear
    from the refresh scheduler merely because its private registry row was not
    backfilled. Published receipts provide the durable source universe; the
    latest successful run_source job provides the recoverable manifest. The
    refresh orchestrator promotes that fallback into REGISTRY_TABLE on first
    execution.
    """
    rows = (
        supabase.table(REGISTRY_TABLE)
        .select("name,value,updated_at")
        .like("name", f"{REGISTRY_PREFIX}%")
        .execute().data or []
    )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        payload = _decode(row.get("value"))
        if not payload:
            continue
        source_id = str(payload.get("source_id") or "").strip()
        if not source_id:
            continue
        payload["registry_backend"] = REGISTRY_TABLE
        payload["registry_updated_at"] = row.get("updated_at")
        out.append(payload)
        seen.add(source_id)

    # Bootstrap missing scheduler entries only from sources that already have a
    # durable canonical "published" receipt. This keeps discovery fail-closed:
    # random runtime jobs do not become recurring production sources.
    receipt_rows = (
        supabase.table("atlas_searchable_source_receipts")
        .select("source_id,probed_at")
        .eq("publish_result", "published")
        .order("probed_at", desc=True)
        .limit(1000)
        .execute().data or []
    )
    receipt_sources: list[str] = []
    receipt_seen: set[str] = set()
    for row in receipt_rows:
        source_id = str((row or {}).get("source_id") or "").strip()
        if not source_id or source_id in receipt_seen:
            continue
        receipt_seen.add(source_id)
        receipt_sources.append(source_id)

    for source_id in receipt_sources:
        if source_id in seen:
            continue
        recovered = latest_runtime_manifest(supabase, source_id)
        if not recovered:
            continue
        out.append(recovered)
        seen.add(source_id)
    return out
