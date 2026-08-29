"""Carly v19: stable E2E recommendation contract and truthful initial breadth.

Initial recommendation responses no longer inherit an arbitrary 2-3 card cap.
The deterministic quality gate builds the eligible set from the same inventory
and profile, fills the first page to six when suitable units exist, and exposes
truthful eligible/remaining counts. Zero additional LLM calls.
"""
from __future__ import annotations

from typing import Any

from . import main_v18 as v18
from .carly_advisor import advisor_score
from .carly_quality_gate import filter_pool

app = v18.app
commercial = v18.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v19-e2e-stable-eligible-set"
_PAGE_SIZE = 6
_FEATURED = 3


def _expand_initial(body: Any, result: Any) -> Any:
    if not isinstance(result, dict) or result.get("phase") != "recommendation":
        return result
    if result.get("token_path") in {"deterministic_continuation", "deterministic_dynamic_preference"}:
        return result

    loaded = v18._unique(list(result.get("loaded_options") or []) or (list(result.get("recommendations") or []) + list(result.get("explore") or [])))
    profile = v18._profile(body, loaded)
    if profile is None:
        return result

    country = getattr(body, "country", None) if body is not None else None
    try:
        raw_pool = v18._unique(list(commercial.legacy._carly_inventory(profile, country=country) or []))
    except Exception:
        return result

    eligible_pool = v18._unique(filter_pool(raw_pool, profile))
    if not eligible_pool:
        return result

    ranked = sorted(eligible_pool, key=lambda c: advisor_score(c, profile), reverse=True)
    seen = {v18._key(c) for c in loaded}
    page = list(loaded)
    for row in ranked:
        if len(page) >= _PAGE_SIZE:
            break
        if v18._key(row) in seen:
            continue
        try:
            card = v18.v17.v16._card(row, profile, len(page) + 1)
        except Exception:
            card = dict(row)
        k = v18._key(card)
        if k in seen:
            continue
        seen.add(k)
        page.append(card)

    page = v18._unique(page[:_PAGE_SIZE])
    eligible_count = max(len(page), len(eligible_pool))
    remaining = max(0, eligible_count - len(page))
    batch = min(_PAGE_SIZE, remaining)

    result["recommendations"] = page[:_FEATURED]
    result["explore"] = page[_FEATURED:]
    result["loaded_options"] = page
    result["loaded_option_ids"] = [v18._key(c) for c in page]
    result["recommendation_count"] = len(result["recommendations"])
    result["explore_count"] = len(result["explore"])
    result["loaded_option_count"] = len(page)
    result["market_pool_size"] = max(int(result.get("market_pool_size") or result.get("pool_size") or 0), len(raw_pool))
    result["eligible_option_count"] = eligible_count
    result["remaining_option_count"] = remaining
    result["more_options_available"] = remaining > 0
    result["more_options_count"] = remaining
    result["more_options_batch_size"] = batch
    result["more_options_cta"] = f"Ver {batch} más" if batch else None
    result["count_semantics_version"] = "v19"
    result["advisor_mode"] = "stable_eligible_set_v19"
    return result


def _patch() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None:
            continue

        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = commercial._request_body(args, kwargs)
            result = __prior(*args, **kwargs)
            return _expand_initial(body, result)

        route.endpoint = endpoint
        dependant.call = endpoint
        break


_patch()
