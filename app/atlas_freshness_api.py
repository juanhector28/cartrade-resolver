from __future__ import annotations

import asyncio
import hmac
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field


FRESHNESS_CONTRACT_VERSION = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def freshness_max_age_seconds() -> int:
    return max(60, int(os.getenv("ATLAS_SEARCH_FRESHNESS_MAX_AGE_SECONDS", "86400")))


def freshness_cutoff_iso() -> str:
    return (_now() - timedelta(seconds=freshness_max_age_seconds())).isoformat()


def _require_token(provided: str | None) -> None:
    expected = (
        os.environ.get("ATLAS_PUBLISH_TOKEN")
        or os.environ.get("ATLAS_BRIDGE_TOKEN")
        or os.environ.get("CRON_TOKEN")
    )
    if not expected:
        raise HTTPException(status_code=503, detail="Atlas freshness token is not configured")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid atlas freshness token")


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _compact(value: Any) -> str:
    return _norm(value).replace(" ", "")


def _identity_ok(row: dict[str, Any], html: str) -> bool:
    make = _norm(row.get("make"))
    model = _compact(row.get("model"))
    try:
        year = str(int(float(row.get("year"))))
    except Exception:
        year = ""
    if not make or not model or not year or model in {"descripcion", "description", "modelo", "model"}:
        return False
    norm = _norm(html[:750000])
    compact = norm.replace(" ", "")
    return make in norm and model in compact and year in norm


def _atlas_meta(row: dict[str, Any] | None) -> dict[str, Any]:
    raw = (row or {}).get("raw_payload")
    if not isinstance(raw, dict):
        return {}
    atlas = raw.get("atlas")
    return atlas if isinstance(atlas, dict) else {}


def _source_rows(supabase: Any, source_id: str, limit: int) -> list[dict[str, Any]]:
    rows = (
        supabase.table("scraped_listings")
        .select("id,url,make,model,year,status,is_addressable,last_seen_at,updated_at,raw_payload")
        .eq("status", "staging")
        .contains("raw_payload", {"atlas": {"source_id": source_id}})
        .limit(limit)
        .execute().data or []
    )
    return [row for row in rows if _atlas_meta(row).get("source_id") == source_id]


class FreshnessRevalidateRequest(BaseModel):
    source_id: str = Field(min_length=3, max_length=240)
    limit: int = Field(default=500, ge=1, le=5000)
    concurrency: int = Field(default=4, ge=1, le=8)
    timeout_seconds: float = Field(default=20.0, ge=3.0, le=60.0)


class FreshnessAgeFixtureRequest(BaseModel):
    source_id: str = Field(min_length=3, max_length=240)
    listing_id: int
    age_seconds: int = Field(ge=60, le=31_536_000)


def install(app: Any, supabase: Any) -> None:
    @app.get("/atlas/freshness/status")
    def atlas_freshness_status():
        return {
            "contract_version": FRESHNESS_CONTRACT_VERSION,
            "clock_field": "last_seen_at",
            "max_age_seconds": freshness_max_age_seconds(),
            "cutoff": freshness_cutoff_iso(),
            "test_mutation_enabled": os.getenv("ATLAS_FRESHNESS_TEST_MUTATION_ENABLED", "0") == "1",
        }

    @app.post("/atlas/freshness/revalidate")
    async def atlas_freshness_revalidate(
        body: FreshnessRevalidateRequest,
        x_atlas_token: str | None = Header(default=None),
    ):
        _require_token(x_atlas_token)
        if supabase is None:
            raise HTTPException(status_code=503, detail="Supabase is not connected")

        source_id = body.source_id.strip()
        rows = _source_rows(supabase, source_id, body.limit)
        semaphore = asyncio.Semaphore(body.concurrency)
        refreshed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            timeout=body.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "AtlasFreshness/1.0"},
        ) as client:
            async def verify(row: dict[str, Any]) -> None:
                url = str(row.get("url") or "").strip()
                if not url:
                    failed.append({"id": row.get("id"), "reason": "url_missing"})
                    return
                try:
                    async with semaphore:
                        response = await client.get(url)
                    if response.status_code < 200 or response.status_code >= 400:
                        failed.append({"id": row.get("id"), "url": url, "reason": "http_error", "status_code": response.status_code})
                        return
                    if not _identity_ok(row, response.text):
                        failed.append({"id": row.get("id"), "url": url, "reason": "identity_not_recovered"})
                        return
                    previous = row.get("last_seen_at")
                    now = _now_iso()
                    result = (
                        supabase.table("scraped_listings")
                        .update({"last_seen_at": now, "updated_at": now})
                        .eq("id", row["id"])
                        .eq("status", "staging")
                        .contains("raw_payload", {"atlas": {"source_id": source_id}})
                        .execute()
                    )
                    if not result.data:
                        failed.append({"id": row.get("id"), "url": url, "reason": "conditional_update_failed"})
                        return
                    refreshed.append({"id": row.get("id"), "url": url, "previous_last_seen_at": previous, "last_seen_at": now})
                except Exception as exc:
                    failed.append({"id": row.get("id"), "url": url, "reason": "verification_exception", "error": str(exc)[:500]})

            await asyncio.gather(*(verify(row) for row in rows))

        return {
            "contract_version": FRESHNESS_CONTRACT_VERSION,
            "source_id": source_id,
            "clock_field": "last_seen_at",
            "attempted_count": len(rows),
            "refreshed_count": len(refreshed),
            "failed_count": len(failed),
            "refreshed": refreshed,
            "failed": failed,
            "completed_at": _now_iso(),
        }

    @app.post("/atlas/freshness/test-age")
    def atlas_freshness_test_age(
        body: FreshnessAgeFixtureRequest,
        x_atlas_token: str | None = Header(default=None),
    ):
        _require_token(x_atlas_token)
        if os.getenv("ATLAS_FRESHNESS_TEST_MUTATION_ENABLED", "0") != "1":
            raise HTTPException(status_code=403, detail="freshness test mutation disabled")
        if supabase is None:
            raise HTTPException(status_code=503, detail="Supabase is not connected")
        aged = (_now() - timedelta(seconds=body.age_seconds)).isoformat()
        result = (
            supabase.table("scraped_listings")
            .update({"last_seen_at": aged})
            .eq("id", body.listing_id)
            .eq("status", "staging")
            .contains("raw_payload", {"atlas": {"source_id": body.source_id.strip()}})
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="fixture listing not found")
        return {
            "contract_version": FRESHNESS_CONTRACT_VERSION,
            "source_id": body.source_id.strip(),
            "listing_id": body.listing_id,
            "last_seen_at": aged,
            "max_age_seconds": freshness_max_age_seconds(),
        }
