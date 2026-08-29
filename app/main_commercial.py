"""Production commercial-advisory layer for Carly.

This is the outermost /carly/chat wrapper. Routine intake is intercepted before
any paid model call, and recommendation quality is enforced deterministically
before the response reaches the UI.
"""
from __future__ import annotations

import os
from typing import Any

from . import main_preview as preview
from .carly_commercial import COMMERCIAL_PROMPT, commercialize_response
from .carly_quality_gate import filter_cards, install_rank_quality

app = preview.app
legacy = preview.legacy
guarded = preview.guarded

RUNTIME_COMPOSITION = "commercial-v4-p0-quality"

# Make the quality gate authoritative for every ranking call made by the legacy
# chat path, preview fastpath, and Decision Room refresh. The wrapper is idempotent.
legacy.rank_cars = install_rank_quality(legacy.rank_cars)

try:
    if COMMERCIAL_PROMPT.strip() not in str(legacy.CARLY_SYSTEM_PROMPT):
        legacy.CARLY_SYSTEM_PROMPT += COMMERCIAL_PROMPT
except Exception:
    pass
try:
    if COMMERCIAL_PROMPT.strip() not in str(guarded._FOLLOWUP_SYSTEM_PROMPT):
        guarded._FOLLOWUP_SYSTEM_PROMPT += COMMERCIAL_PROMPT
except Exception:
    pass


@app.get("/carly/runtime")
def carly_runtime():
    return {
        "ok": True,
        "composition": RUNTIME_COMPOSITION,
        "token_strategy": "rules-first",
        "intake_fastpath": True,
        "quality_gate": True,
        "default_curated_recommendations": 3,
        "followup_max_tokens": 320,
        "git_commit": os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or None,
    }


def _request_body(args, kwargs):
    try:
        return guarded._request_body(args, kwargs)
    except Exception:
        return None


def _profile_for_result(result: Any):
    if not isinstance(result, dict):
        return None
    data = result.get("profile")
    if not isinstance(data, dict):
        return None
    try:
        return legacy.profile_from_extraction(dict(data))
    except Exception:
        return None


def _final_quality_gate(result: Any) -> Any:
    """UI safety net: only three curated cards, never fill with weak inventory."""
    if not isinstance(result, dict) or result.get("phase") != "recommendation":
        return result
    profile = _profile_for_result(result)
    if profile is None:
        return result

    cards = filter_cards(list(result.get("recommendations") or []), profile, limit=3)
    result["recommendations"] = cards
    result["favorite"] = cards[0] if cards else None
    result["recommendation_count"] = len(cards)
    result["recommendation_quality_policy"] = "quality_over_quota"

    curated_urls = {c.get("url") for c in cards if c.get("url")}
    explore = filter_cards(list(result.get("explore") or []), profile, limit=18)
    result["explore"] = [c for c in explore if c.get("url") not in curated_urls][:12]

    decision = result.get("decision")
    if isinstance(decision, dict):
        decision_cards = filter_cards(list(decision.get("recommendations") or []), profile, limit=3)
        decision["recommendations"] = decision_cards
        if "favorite" in decision:
            decision["favorite"] = decision_cards[0] if decision_cards else None

    return result


def _deterministic_outer_fastpath(body, messages: list[Any]) -> dict | None:
    """Resolve common intake before entering any older/LLM route layer."""
    if body is None or (getattr(body, "shown_cars", None) or []):
        return None

    country = getattr(body, "country", None)
    fast = preview.extract_fast_profile(messages, country=country)
    if fast:
        try:
            policy = preview.preview_policy(messages, has_visible_cars=False)
            direct = preview._preview_result(
                body,
                {**policy, "reason": "outer_deterministic_fastpath"},
                data=fast,
            )
            if direct is not None:
                direct["token_path"] = "deterministic"
                return direct
        except Exception:
            legacy.log.exception("Carly outer deterministic preview failed")

    blocker = preview.deterministic_intake_reply(messages, country=country)
    if blocker:
        # Keep the one-question fastpath exactly as designed. Do not expand a
        # concise budget question into a price-vs-payment explanation.
        return {
            "phase": "conversation",
            "reply": blocker,
            "token_path": "deterministic",
        }
    return None


def _patch_commercial_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue
        prior = endpoint

        def commercial_endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = _request_body(args, kwargs)
            messages = list(getattr(body, "messages", None) or []) if body is not None else []

            direct = _deterministic_outer_fastpath(body, messages)
            if direct is not None:
                direct = _final_quality_gate(direct)
                # A deterministic intake question is already product-approved.
                # Do not run it through legacy budget-question rewriting.
                if direct.get("phase") == "conversation":
                    return direct
                return commercialize_response(direct, messages=messages)

            result = __prior(*args, **kwargs)
            result = _final_quality_gate(result)
            return commercialize_response(result, messages=messages)

        route.endpoint = commercial_endpoint
        dependant.call = commercial_endpoint
        break


_patch_commercial_route()
