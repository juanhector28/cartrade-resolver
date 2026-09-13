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
import re
from typing import Any

from . import carly_fastpath as fastpath
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

        allowed = [str(x).strip() for x in (c.get("allowed_brands") or []) if str(x).strip()]
        if len(allowed) == 1:
            q = q.ilike("make", allowed[0])
        elif allowed:
            q = q.in_("make", allowed)

        response = q.order("updated_at", desc=True).limit(900).execute()
        rows = [dict(r) for r in (response.data or [])]
        log.warning(
            "CARLY_V50_SAFE_RETRIEVAL country=%s rows=%s cutoff=%s allowed_brands=%s",
            country,
            len(rows),
            freshness_cutoff_iso(),
            allowed,
        )
        return rows
    except Exception:
        log.exception("CARLY_V50_SAFE_RETRIEVAL failed closed country=%s", country)
        return []


# v46's bounded retrieval calls this module global dynamically. Replacing the
# underlying function preserves v46's preselection caps while making its source
# pool fail-closed and consistent with the canonical Atlas visibility contract.
v46._ORIG_QUERY_ROWS = _safe_focused_query_rows

# P0 demo latency hotfix: v46 already bounds explicit body searches, but its
# action parser recognized "busco un SUV" and missed the equally explicit
# "busco un Mazda SUV" because a make appeared between the verb and body type.
# That miss prevented v47's single-pass route and allowed an unnecessary broad
# 900-row inherited rank before the bounded authoritative rebuild.
_brand_token = "|".join(
    sorted((re.escape(alias) for alias in v31._BRAND_ALIASES), key=len, reverse=True)
)
v46._BODY_ACTION = re.compile(
    r"\b(?:estoy\s+buscando|ando\s+buscando|busco|quiero|necesito)\s+"
    r"(?:un|una)?\s*(?:(?:" + _brand_token + r")\s+)?"
    r"(suv|pickup|pick[- ]?up|sed[aá]n|hatch(?:back)?)\b",
    re.I,
)
if v46._explicit_body("Busco un Mazda SUV entre USD 12,000 y 25,000") != "suv":
    raise RuntimeError("Carly branded-body fastpath self-check failed")

# The zero-token fast profile used to treat a bare brand mention as ambiguous
# unless the buyer said "solo" or "prefiero". A direct purchase request such as
# "busco un Mazda SUV" is not casual brand context: it is an explicit requested
# make. Promote only this narrow action+brand syntax to a hard brand constraint;
# all softer mentions keep the previous conservative behavior.
_original_brand_constraints = fastpath._brand_constraints


def _brand_constraints_with_direct_request(text: str):
    required, preferred, mentioned = _original_brand_constraints(text)
    required = list(required or [])
    preferred = list(preferred or [])
    if mentioned and not required and not preferred:
        normalized = fastpath._norm(text)
        for brand in fastpath._BRANDS:
            normalized_brand = fastpath._norm(brand)
            direct = re.search(
                r"\b(?:estoy\s+buscando|ando\s+buscando|busco|quiero|necesito)\s+"
                r"(?:un|una)?\s*" + re.escape(normalized_brand) + r"\b",
                normalized,
                re.I,
            )
            if direct:
                required.append(brand)
                break
    return required, preferred, mentioned


fastpath._brand_constraints = _brand_constraints_with_direct_request

# v47 merged monthly/body facts from the fast profile but historically dropped
# required make constraints. Propagate only hard require_brands into the focused
# retrieval contract; preferred brands remain ranking preferences and are not
# turned into filters.
_original_merge_fast_constraints = v47._merge_fast_constraints


def _merge_fast_constraints_with_required_brands(c: dict[str, Any], fast: dict[str, Any]) -> dict[str, Any]:
    out = dict(_original_merge_fast_constraints(c, fast))
    required = [str(x).strip() for x in (fast.get("require_brands") or []) if str(x).strip()]
    if required:
        out["allowed_brands"] = required
    return out


v47._merge_fast_constraints = _merge_fast_constraints_with_required_brands

# Exact regression fixture from the live G&T demo rehearsal. It protects the
# complete intent contract: Mazda + SUV + $550/month must survive all deterministic
# parsing and constraint merging before any inventory query is allowed to run.
_demo_messages = [
    {"role": "user", "content": "Busco un Mazda SUV entre USD 12,000 y 25,000 en Guatemala"},
    {"role": "assistant", "content": "Entendido, buscas un Mazda SUV en Guatemala con un rango de $12,000 a $25,000. ¿Para qué lo vas a usar principalmente?"},
    {"role": "user", "content": "trabajo y dejar a mis hijos al colegio"},
    {"role": "assistant", "content": "Entendido. ¿Qué cuota mensual te queda cómoda?"},
    {"role": "user", "content": "550 al mes"},
]
_demo_repaired = v47.commercial._repair_missing_monthly_context(_demo_messages, country="gt")
_demo_fast = v47.commercial.preview.extract_fast_profile(_demo_repaired, country="gt")
if not isinstance(_demo_fast, dict):
    raise RuntimeError("Carly exact demo fast-profile self-check failed")
if float(_demo_fast.get("max_monthly") or 0) != 550.0:
    raise RuntimeError(f"Carly exact demo monthly self-check failed: {_demo_fast.get('max_monthly')!r}")
if [x.lower() for x in (_demo_fast.get("require_brands") or [])] != ["mazda"]:
    raise RuntimeError(f"Carly exact demo brand self-check failed: {_demo_fast.get('require_brands')!r}")
_demo_merged = v47._merge_fast_constraints({"monthly_max": 700.0, "require_body": None}, _demo_fast)
if float(_demo_merged.get("monthly_max") or 0) != 550.0:
    raise RuntimeError(f"Carly exact demo constraint merge failed: {_demo_merged.get('monthly_max')!r}")
if [x.lower() for x in (_demo_merged.get("allowed_brands") or [])] != ["mazda"]:
    raise RuntimeError(f"Carly exact demo brand merge failed: {_demo_merged.get('allowed_brands')!r}")
if v46._explicit_body(_demo_messages[0]["content"]) != "suv":
    raise RuntimeError("Carly exact demo SUV self-check failed")

try:
    v47.v44.v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = (
        "commercial-v50-safe-fresh-retrieval"
    )
except Exception:
    pass

log.warning(
    "CARLY_V50_SAFE_RETRIEVAL installed staging=true freshness=true fail_closed=true "
    "branded_body_fastpath=true exact_demo_brand=mazda exact_demo_monthly=550 brand_filter=true"
)
