"""Carly v50: fail-closed focused retrieval + buyer-truth single-pass.

The final recommendation path must derive hard facts from buyer messages only.
This layer keeps all existing scoring/safety gates while ensuring the common
single-pass route cannot lose an explicit make, body type, or monthly ceiling.
"""
from __future__ import annotations

import logging
import re
import time
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
            "CARLY_V50_SAFE_RETRIEVAL country=%s rows=%s cutoff=%s allowed_brands=%s monthly=%s",
            country, len(rows), freshness_cutoff_iso(), allowed, c.get("monthly_max"),
        )
        return rows
    except Exception:
        log.exception("CARLY_V50_SAFE_RETRIEVAL failed closed country=%s", country)
        return []


v46._ORIG_QUERY_ROWS = _safe_focused_query_rows

_brand_token = "|".join(
    sorted((re.escape(alias) for alias in v31._BRAND_ALIASES), key=len, reverse=True)
)
v46._BODY_ACTION = re.compile(
    r"\b(?:estoy\s+buscando|ando\s+buscando|busco|quiero|necesito)\s+"
    r"(?:un|una)?\s*(?:(?:" + _brand_token + r")\s+)?"
    r"(suv|pickup|pick[- ]?up|sed[aá]n|hatch(?:back)?)\b",
    re.I,
)


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
    if not out.get("require_body"):
        body_req = v46._explicit_body(buyer_text)
        if body_req:
            out["require_body"] = body_req
    return out


v46.v40._constraints = _constraints_with_user_truth
v39._constraints = _constraints_with_user_truth
v46.v37._constraints = _constraints_with_user_truth
v31._constraints = _constraints_with_user_truth

_original_merge_fast_constraints = v47._merge_fast_constraints


def _merge_fast_constraints_v50(c: dict[str, Any], fast: dict[str, Any]) -> dict[str, Any]:
    out = dict(_original_merge_fast_constraints(c, fast))
    required = [str(x).strip() for x in (fast.get("require_brands") or []) if str(x).strip()]
    if required and not out.get("allowed_brands"):
        out["allowed_brands"] = required
    return out


v47._merge_fast_constraints = _merge_fast_constraints_v50


def _single_pass_v50(body: Any, messages: list[Any]) -> dict | None:
    """Authoritative single-pass with hard buyer facts reasserted at query time."""
    if body is None or (getattr(body, "shown_cars", None) or []):
        return None

    country = getattr(body, "country", None)
    parse_messages = v47.commercial._repair_missing_monthly_context(messages, country=country)
    fast = v47.commercial.preview.extract_fast_profile(parse_messages, country=country)
    if not isinstance(fast, dict):
        return None

    c = _merge_fast_constraints_v50(_constraints_with_user_truth(body), fast)
    # Final defense-in-depth reassertion immediately before retrieval.
    buyer_text = v31._text(body)
    brand = _direct_requested_brand(buyer_text)
    if brand:
        c["allowed_brands"] = [brand]
    monthly = v28._extract_monthly(body)
    if monthly is not None:
        c["monthly_max"] = float(monthly)
    body_req = v46._explicit_body(buyer_text)
    if body_req:
        c["require_body"] = body_req

    if not v39._should_retrieve(c):
        return None

    policy = v47.commercial.preview.preview_policy(parse_messages, has_visible_cars=False)
    started = time.perf_counter()
    result = v39._rebuild(
        body,
        {"profile": dict(fast), "token_path": "deterministic-single-pass"},
        c,
    )
    if not isinstance(result, dict):
        return None

    result["recommendation_stage"] = "preview"
    result["preview"] = True
    result["preview_reason"] = "outer_single_pass_fastpath"
    result["preview_question_count"] = int(policy.get("questions") or 0)
    result["refinement_available"] = True
    result["show_market_animation"] = True
    result["replace_recommendations"] = True
    result["clear_recommendations"] = False
    result["token_path"] = "deterministic-single-pass"
    result = v47.commercial.preview.room.state.apply_ui_contract(result)
    result = v47.commercial._final_quality_gate(result)
    result = v47.commercial.commercialize_response(result, messages=messages)

    log.warning(
        "CARLY_V50_SINGLE_PASS elapsed_ms=%.1f recommendations=%s pool_size=%s body=%s monthly=%s allowed_brands=%s",
        (time.perf_counter() - started) * 1000,
        len(result.get("recommendations") or []),
        result.get("pool_size"),
        c.get("require_body"),
        c.get("monthly_max"),
        c.get("allowed_brands"),
    )
    return result


# The existing v47 route closure resolves _single_pass from the v47 module at
# request time, so replacing this global changes the live path without stacking
# another route wrapper.
v47._single_pass = _single_pass_v50

# Byte-for-byte regression fixture from the observed failure, including Carly's
# incorrect 100-km sentence. Buyer facts must remain Mazda + SUV + $550/month.
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

try:
    v47.v44.v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = (
        "commercial-v50-buyer-truth-single-pass"
    )
except Exception:
    pass

log.warning(
    "CARLY_V50_BUYER_TRUTH installed exact_demo_brand=mazda exact_demo_body=suv exact_demo_monthly=550"
)
