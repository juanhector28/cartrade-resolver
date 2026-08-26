"""Production composition root for Carly guardrails.

The existing FastAPI implementation stays in app.main. This module patches only
Carly's decision path at import time and exposes the same `app` object. Railway
points here so the rollout is easy to revert while the guardrails prove out.
"""
from __future__ import annotations

import contextvars
import re
from typing import Any

from . import main as legacy
from . import carly_profile as profile_module
from . import carly_ranking as ranking
from .carly_guardrails import (
    GUARDRAIL_PROMPT,
    apply_explicit_facts,
    canonical_context_line,
    extract_explicit_facts,
    passes_pinned_constraints,
    pin_hard_constraints,
)

_facts_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "carly_explicit_facts", default={}
)
_market_refs_ctx: contextvars.ContextVar[list] = contextvars.ContextVar(
    "carly_market_refs", default=[]
)

_original_clean_frontend_context = legacy._clean_frontend_context
_original_profile_from_extraction = legacy.profile_from_extraction
_original_passes_filters = ranking.passes_filters
_original_inventory = legacy._carly_inventory
_original_rank_cars = legacy.rank_cars


def _sanitize_frontend_meta(items: list[str]) -> list[str]:
    """Keep location metadata but remove radius numbers that can become fake usage."""
    cleaned = []
    for item in items or []:
        text = str(item or "")
        text = re.sub(
            r"\b(?:radio|radius|rango)\s*:?\s*\d+(?:[.,]\d+)?\s*km\b",
            "",
            text,
            flags=re.I,
        )
        text = re.sub(r"\s*[·|]\s*\d+(?:[.,]\d+)?\s*km\b", "", text, flags=re.I)
        text = re.sub(r"\s{2,}", " ", text).strip(" ;,·|")
        if text:
            cleaned.append(text)
    return cleaned


def _clean_frontend_context_guarded(messages):
    cleaned, meta = _original_clean_frontend_context(messages)
    facts = extract_explicit_facts(messages)
    _facts_ctx.set(dict(facts))

    safe_meta = _sanitize_frontend_meta(meta)
    canonical = canonical_context_line(facts)
    if canonical:
        safe_meta.append(canonical)
    return cleaned, safe_meta


def _profile_from_extraction_guarded(data: dict):
    facts = _facts_ctx.get({})
    apply_explicit_facts(data, facts)
    profile = _original_profile_from_extraction(data)
    return pin_hard_constraints(profile, data)


def _passes_filters_guarded(car, profile):
    if car.get("_carly_reference_only"):
        return False
    if not _original_passes_filters(car, profile):
        return False
    return passes_pinned_constraints(car, profile)


def _load_market_references(country: str | None, limit: int = 5000) -> list[dict]:
    """Broad, profile-independent market set for stable price comparisons."""
    if not legacy.supabase:
        return []
    try:
        q = (
            legacy.supabase.table("scraped_listings")
            .select("url,make,model,price_usd")
            .eq("status", "staging")
            .not_.is_("price_usd", "null")
            .limit(limit)
        )
        if country:
            q = q.eq("country", country)
        return q.execute().data or []
    except Exception:
        legacy.log.exception("Carly market-reference pull failed")
        return []


def _carly_inventory_guarded(profile, country=None, pool=600):
    """Return only rows that satisfy every pinned hard constraint."""
    _market_refs_ctx.set(_load_market_references(country))

    fetch_pool = min(3000, max(int(pool or 600) * 3, int(pool or 600)))
    rows = _original_inventory(profile, country=country, pool=fetch_pool)
    eligible = [r for r in rows if ranking.passes_filters(r, profile)]
    return eligible[: int(pool or 600)]


def _rank_cars_guarded(cars, profile, top_n=5):
    """Rank eligible cars while comparing price against the broader market."""
    live = list(cars or [])
    live_urls = {r.get("url") for r in live if r.get("url")}
    references = []
    for row in _market_refs_ctx.get([]):
        if row.get("url") and row.get("url") in live_urls:
            continue
        ref = dict(row)
        ref["_carly_reference_only"] = True
        references.append(ref)
    return _original_rank_cars(live + references, profile, top_n=top_n)


def _patch_empty_result_message():
    """Make zero-match behavior explicit instead of implying silent relaxation."""
    for route in getattr(legacy.app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue

        original_endpoint = endpoint

        def guarded_endpoint(*args: Any, __original=original_endpoint, **kwargs: Any):
            result = __original(*args, **kwargs)
            if (
                isinstance(result, dict)
                and result.get("phase") == "recommendation"
                and not result.get("recommendations")
            ):
                result["reply"] = (
                    "Con tus limites exactos no encontre una opcion suficientemente fuerte. "
                    "No voy a saltarme una restriccion que me diste. Si quieres abrir una, "
                    "te digo exactamente cual conviene flexibilizar y que opciones aparecen."
                )
            return result

        route.endpoint = guarded_endpoint
        dependant.call = guarded_endpoint
        break


ranking.passes_filters = _passes_filters_guarded
ranking.rank_cars = _rank_cars_guarded
legacy._clean_frontend_context = _clean_frontend_context_guarded
legacy.profile_from_extraction = _profile_from_extraction_guarded
legacy._carly_inventory = _carly_inventory_guarded
legacy.rank_cars = _rank_cars_guarded

profile_module.CARLY_SYSTEM_PROMPT = (
    profile_module.CARLY_SYSTEM_PROMPT + "\n\n" + GUARDRAIL_PROMPT
)
legacy.CARLY_SYSTEM_PROMPT = profile_module.CARLY_SYSTEM_PROMPT

_patch_empty_result_message()

app = legacy.app
