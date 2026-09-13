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
v28 = v31.v29.v28
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

# Direct buyer requests such as "busco un Mazda SUV" are hard make intent.
# This narrow parser is buyer-text-only; assistant text can never create or
# widen a brand constraint.
def _direct_requested_brand(text: str) -> str | None:
    normalized = v28._norm(text or "")
    for alias, canonical in v31._BRAND_ALIASES.items():
        if re.search(
            r"\b(?:estoy\s+buscando|ando\s+buscando|busco|quiero|necesito)\s+"
            r"(?:un|una)?\s*" + re.escape(v28._norm(alias)) + r"\b",
            normalized,
            re.I,
        ):
            return canonical
    return None


# Keep the zero-token fast profile aligned for common journeys.
_original_brand_constraints = fastpath._brand_constraints


def _brand_constraints_with_direct_request(text: str):
    required, preferred, mentioned = _original_brand_constraints(text)
    required = list(required or [])
    preferred = list(preferred or [])
    direct = _direct_requested_brand(text)
    if direct and not required:
        required = [direct]
    return required, preferred, mentioned


fastpath._brand_constraints = _brand_constraints_with_direct_request

# Authoritative user-truth wrapper. v47's fast profile is an optimization, not
# the owner of hard facts. Re-derive explicit make and monthly ceiling from the
# buyer-only request body immediately before retrieval so stale/incorrect Carly
# prose cannot contaminate the search contract.
_prior_constraints = v46.v40._constraints


def _constraints_with_user_truth(body: Any) -> dict[str, Any]:
    out = dict(_prior_constraints(body))
    buyer_text = v31._text(body)
    brand = _direct_requested_brand(buyer_text)
    if brand:
        out["allowed_brands"] = [brand]
    monthly = v28._extract_monthly(body)
    if monthly is not None:
        out["monthly_max"] = float(monthly)
    return out


v46.v40._constraints = _constraints_with_user_truth
v39._constraints = _constraints_with_user_truth
v46.v37._constraints = _constraints_with_user_truth
v31._constraints = _constraints_with_user_truth

# Retain fast-profile propagation as defense in depth for hard brand intent.
_original_merge_fast_constraints = v47._merge_fast_constraints


def _merge_fast_constraints_with_required_brands(c: dict[str, Any], fast: dict[str, Any]) -> dict[str, Any]:
    out = dict(_original_merge_fast_constraints(c, fast))
    required = [str(x).strip() for x in (fast.get("require_brands") or []) if str(x).strip()]
    if required and not out.get("allowed_brands"):
        out["allowed_brands"] = required
    return out


v47._merge_fast_constraints = _merge_fast_constraints_with_required_brands

# Byte-for-byte regression fixture from the live G&T demo failure, including
# Carly's incorrect 100-km sentence. Hard buyer facts must remain Mazda + SUV +
# $550/month regardless of assistant prose.
_demo_messages = [
    {"role": "user", "content": "Busco un Mazda SUV entre USD 12,000 y 25,000 en Guatemala"},
    {"role": "assistant", "content": "Entendido, buscas un Mazda SUV en Guatemala con un rango de $12,000 a $25,000 y ya sé que manejas unos 100 km al día. ¿Para qué lo vas a usar principalmente: trabajo diario, familia, negocio, o algo más?"},
    {"role": "user", "content": "trabajo y dejar a mis hijos al colegio"},
    {"role": "assistant", "content": "Entendido. ¿Qué cuota mensual te queda cómoda?"},
    {"role": "user", "content": "550 al mes"},
]
_demo_body = {"messages": _demo_messages, "country": "gt", "shown_cars": []}
_demo_constraints = _constraints_with_user_truth(_demo_body)
if [x.lower() for x in (_demo_constraints.get("allowed_brands") or [])] != ["mazda"]:
    raise RuntimeError(f"Carly exact demo authoritative brand failed: {_demo_constraints.get('allowed_brands')!r}")
if float(_demo_constraints.get("monthly_max") or 0) != 550.0:
    raise RuntimeError(f"Carly exact demo authoritative monthly failed: {_demo_constraints.get('monthly_max')!r}")
if _demo_constraints.get("require_body") != "suv":
    raise RuntimeError(f"Carly exact demo authoritative body failed: {_demo_constraints.get('require_body')!r}")

_demo_repaired = v47.commercial._repair_missing_monthly_context(_demo_messages, country="gt")
_demo_fast = v47.commercial.preview.extract_fast_profile(_demo_repaired, country="gt")
if not isinstance(_demo_fast, dict):
    raise RuntimeError("Carly exact demo fast-profile self-check failed")
_demo_merged = v47._merge_fast_constraints(_demo_constraints, _demo_fast)
if float(_demo_merged.get("monthly_max") or 0) != 550.0:
    raise RuntimeError(f"Carly exact demo merged monthly failed: {_demo_merged.get('monthly_max')!r}")
if [x.lower() for x in (_demo_merged.get("allowed_brands") or [])] != ["mazda"]:
    raise RuntimeError(f"Carly exact demo merged brand failed: {_demo_merged.get('allowed_brands')!r}")

try:
    v47.v44.v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = (
        "commercial-v50-safe-fresh-retrieval"
    )
except Exception:
    pass

log.warning(
    "CARLY_V50_SAFE_RETRIEVAL installed staging=true freshness=true fail_closed=true "
    "buyer_truth=true exact_demo_brand=mazda exact_demo_body=suv exact_demo_monthly=550"
)
