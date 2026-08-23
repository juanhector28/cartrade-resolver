from __future__ import annotations

import hmac
import os
from collections import Counter
from typing import Any

from fastapi import Header, HTTPException, Query


SAFE_COLUMNS = (
    "id",
    "source",
    "country",
    "url",
    "title",
    "make",
    "model",
    "year",
    "km",
    "price_usd",
    "currency",
    "fuel_type",
    "transmission",
    "location",
    "photos",
    "photo_count",
    "primary_photo",
    "scraped_at",
    "updated_at",
    "last_seen_at",
    "listing_state",
)

_COUNTRIES = {"gt", "sv", "hn", "ni", "cr", "pa", "bz"}


def _require_read_token(provided: str | None) -> None:
    expected = (
        os.environ.get("ATLAS_INVENTORY_READ_TOKEN")
        or os.environ.get("ATLAS_BRIDGE_TOKEN")
        or os.environ.get("CRON_TOKEN")
    )
    if not expected:
        raise HTTPException(status_code=503, detail="Atlas inventory token is not configured")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid atlas inventory token")


def _clean_country(country: str | None) -> str | None:
    if country is None:
        return None
    value = country.strip().lower()
    if value not in _COUNTRIES:
        raise HTTPException(status_code=422, detail="unsupported country")
    return value


def _safe_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        {key: row.get(key) for key in SAFE_COLUMNS if key in row}
        for row in (rows or [])
    ]


def query_inventory(
    supabase: Any,
    *,
    country: str | None = None,
    source_id: str | None = None,
    make: str | None = None,
    model: str | None = None,
    min_year: int | None = None,
    max_price: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not connected")

    country = _clean_country(country)
    query = (
        supabase.table("scraped_listings")
        .select(",".join(SAFE_COLUMNS), count="exact")
        .eq("status", "atlas_shadow")
    )
    if country:
        query = query.eq("country", country)
    if source_id:
        query = query.contains("raw_payload", {"atlas": {"source_id": source_id.strip()}})
    if make:
        query = query.ilike("make", f"%{make.strip()}%")
    if model:
        query = query.ilike("model", f"%{model.strip()}%")
    if min_year is not None:
        query = query.gte("year", min_year)
    if max_price is not None:
        query = query.lte("price_usd", max_price)

    response = query.order("updated_at", desc=True).range(offset, offset + limit - 1).execute()
    rows = _safe_rows(response.data)
    total = response.count if getattr(response, "count", None) is not None else len(rows)
    return {
        "mode": "shadow",
        "addressable": False,
        "total": total,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "items": rows,
    }


def inventory_summary(supabase: Any) -> dict[str, Any]:
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not connected")

    response = (
        supabase.table("scraped_listings")
        .select("country,source,updated_at", count="exact")
        .eq("status", "atlas_shadow")
        .order("updated_at", desc=True)
        .limit(5000)
        .execute()
    )
    rows = response.data or []
    total = response.count if getattr(response, "count", None) is not None else len(rows)
    by_country = Counter(str(row.get("country") or "unknown").upper() for row in rows)
    by_source = Counter(str(row.get("source") or "unknown") for row in rows)
    latest = max((str(row.get("updated_at")) for row in rows if row.get("updated_at")), default=None)
    return {
        "mode": "shadow",
        "addressable": False,
        "total": total,
        "by_country": dict(sorted(by_country.items())),
        "by_source": dict(sorted(by_source.items())),
        "latest_updated_at": latest,
        "truncated": total > len(rows),
    }


def install(app: Any, supabase: Any) -> None:
    @app.get("/atlas/inventory")
    def atlas_inventory(
        country: str | None = None,
        source_id: str | None = None,
        make: str | None = None,
        model: str | None = None,
        min_year: int | None = Query(default=None, ge=1950, le=2100),
        max_price: float | None = Query(default=None, gt=0),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=10000),
        x_atlas_token: str | None = Header(default=None),
    ):
        _require_read_token(x_atlas_token)
        return query_inventory(
            supabase,
            country=country,
            source_id=source_id,
            make=make,
            model=model,
            min_year=min_year,
            max_price=max_price,
            limit=limit,
            offset=offset,
        )

    @app.get("/atlas/inventory/summary")
    def atlas_inventory_summary(x_atlas_token: str | None = Header(default=None)):
        _require_read_token(x_atlas_token)
        return inventory_summary(supabase)
