"""Carly v17: one coherent recommendation set with truthful six-at-a-time paging.

The UI has two visual buckets (featured recommendations + "tambien consideraria").
Continuation pages therefore expose six cards as 3 featured + 3 explore cards so
"Ver 6 mas" really renders six without changing the existing frontend contract.
All counts derive from the same eligible ranked set; raw market size never drives
continuation CTAs. Zero LLM calls are added.
"""
from __future__ import annotations

from typing import Any

from . import main_v16 as v16

app = v16.app
commercial = v16.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v17-coherent-recommendation-set"

_PAGE_SIZE = 6
_FEATURED_SIZE = 3


def _decorate_set(result: Any) -> Any:
    if not isinstance(result, dict) or result.get("phase") != "recommendation":
        return result

    featured = list(result.get("recommendations") or [])
    explore = list(result.get("explore") or [])
    loaded_cards = featured + explore

    market = int(result.get("market_pool_size") or result.get("pool_size") or 0)
    eligible = int(
        result.get("eligible_option_count")
        or result.get("quality_candidate_count")
        or len(loaded_cards)
    )

    # v15/v16 continuation may return six cards entirely in recommendations.
    # Existing frontend renders a maximum of three featured cards, while explore
    # is rendered in the secondary rail. Split the page contract deterministically
    # so a six-card page is actually visible as six cards.
    if result.get("token_path") in {"deterministic_continuation", "deterministic_dynamic_preference"} and len(featured) > _FEATURED_SIZE and not explore:
        page = featured[:_PAGE_SIZE]
        featured = page[:_FEATURED_SIZE]
        explore = page[_FEATURED_SIZE:_PAGE_SIZE]
        result["recommendations"] = featured
        result["explore"] = explore
        result["recommendation_count"] = len(featured)
        result["explore_count"] = len(explore)
        loaded_cards = featured + explore

    loaded = len(loaded_cards)
    remaining = max(0, eligible - loaded)

    result["market_pool_size"] = market
    result["eligible_option_count"] = eligible
    result["loaded_option_count"] = loaded
    result["featured_option_count"] = len(featured)
    result["secondary_option_count"] = len(explore)
    result["remaining_option_count"] = remaining
    result["more_options_available"] = remaining > 0
    result["more_options_count"] = remaining
    result["page_size"] = _PAGE_SIZE
    result["recommendation_set_semantics"] = {
        "market_pool": "vehicles_considered",
        "eligible_set": "vehicles_that_pass_current_buyer_filters",
        "featured_results": "top_ranked_cards_shown_first",
        "secondary_results": "additional_cards_loaded_on_same_page",
        "remaining_results": "eligible_cards_not_yet_loaded",
    }

    # Give the frontend a single source of truth if/when it migrates away from
    # the two historical visual buckets.
    result["loaded_options"] = loaded_cards
    result["loaded_option_ids"] = [v16.v15._key(c) for c in loaded_cards]

    # Copy changes from older layers can claim a fixed number of alternatives.
    # Replace only deterministic page replies, where we know the exact truth.
    if result.get("token_path") in {"deterministic_continuation", "deterministic_dynamic_preference"}:
        if loaded:
            result["reply"] = (
                f"Encontré {loaded} opciones adicionales que mantienen tus criterios y no repiten las anteriores."
                + (f" Quedan {remaining} más que todavía pasan el filtro." if remaining else " Estas son las últimas que pasan el filtro actual.")
            )
        result["llm_calls"] = 0
        result["advisor_mode"] = "coherent_recommendation_set_v17"

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
            return _decorate_set(__prior(*args, **kwargs))

        route.endpoint = endpoint
        dependant.call = endpoint
        break


_patch()
