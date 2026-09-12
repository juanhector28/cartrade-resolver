"""Carly v50: fail-closed source isolation + freshness on focused retrieval.

The legacy /carly/search path already enforces status=staging and the Atlas
freshness contract, but v39's focused retrieval (used by the v47 single-pass
path) queried country + is_addressable + listing_state directly. That allowed
addressable atlas_shadow rows, or stale staging rows, to enter an otherwise
valid Carly shortlist.

v50 patches the underlying focused-query function used by v46 while preserving
all existing v46 bounding, v47 single-pass, v48 typed constraints, and v49 unit
safety. Retrieval now requires:
- status = staging
- is_addressable = true
- listing_state = indexed
- last_seen_at inside the canonical Atlas freshness window

If the safe query fails, it returns no rows rather than falling back to a less
strict retrieval path.
"""
from __future__ import annotations

import logging
from typing import Any

from . import main_v49 as v49
from .atlas_freshness_api import freshness_cutoff_iso

app = v49.app
v48 = v49.v48
v47 = v48.v47
v46 = v47.v46
v39 = v47.v39
v31 = v39.v31
legacy = v39.legacy

log = logging.getLogger("carly.retrieval.v50")


def _safe_focused_query_rows(c: dict[str, Any], country: str) -> list[dict]:
    """Focused Supabase retrieval with production visibility + freshness gates."""
    client = getattr(legacy, "supabase", None)
    if client is None:
        return []
    try:
        q = (
            client.table("scraped_listings").select(v31._SELECT)
            .eq("country", country)
            .eq("status", "staging")
            .eq("is_addressable", True)
            .eq("listing_state", "indexed")
            .gte("last_seen_at", freshness_cutoff_iso())
        )

        exact = c.get("exact")
        if exact:
            q = q.ilike("make", f"%{exact[0]}%")
        if c.get("min_year"):
            q = q.gte("year", int(c["min_year"]))
        if c.get("require_transmission") == "automatic":
            q = q.ilike("transmission", "%Auto%")
        elif c.get("require_transmission") == "manual":
            q = q.ilike("transmission", "%Manual%")

        price_cap = None
        if c.get("total_budget"):
            price_cap = float(c["total_budget"])
        if c.get("monthly_max"):
            implied = float(c["monthly_max"]) / 0.0238 * 1.03
            price_cap = min(price_cap, implied) if price_cap else implied
        if price_cap:
            q = q.lte("price_usd", round(price_cap, 2))

        allowed = list(c.get("allowed_brands") or [])
        if allowed:
            q = q.in_("make", allowed)

        response = q.order("updated_at", desc=True).limit(900).execute()
        rows = [dict(r) for r in (response.data or [])]
        log.warning(
            "CARLY_V50_SAFE_RETRIEVAL country=%s rows=%s cutoff=%s",
            country,
            len(rows),
            freshness_cutoff_iso(),
        )
        return rows
    except Exception:
        log.exception("CARLY_V50_SAFE_RETRIEVAL failed closed country=%s", country)
        return []


# v46's bounded retrieval calls this module global dynamically. Replacing the
# underlying function preserves v46's preselection caps while making its source
# pool fail-closed and consistent with the canonical Atlas visibility contract.
v46._ORIG_QUERY_ROWS = _safe_focused_query_rows

try:
    v47.v44.v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = (
        "commercial-v50-safe-fresh-retrieval"
    )
except Exception:
    pass

log.warning("CARLY_V50_SAFE_RETRIEVAL installed staging=true freshness=true fail_closed=true")
