"""Carly v10 composition: tighter exploration + verification-aware briefs.

Goals:
- preserve v9's stable zero-token intake and recommendation intelligence
- stop recommendation quality from dissolving as the user scrolls
- answer normal pros/cons enquiries with short, hierarchical, CarTrade-aware briefs
- keep these paths deterministic and at zero Anthropic calls
"""
from __future__ import annotations

from typing import Any

from . import main_v9 as v9
from .carly_advisor import advisor_score, curate
from .carly_quality_gate import filter_cards
from .carly_vehicle_brief import build_vehicle_brief

app = v9.app
commercial = v9.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v10-verification-briefs"

STRONG_THRESHOLD = 60.0
EXPLORE_THRESHOLD = 55.0
MAX_STRONG = 3
MAX_EXPLORE = 6


def _request_body(args, kwargs):
    try:
        return commercial._request_body(args, kwargs)
    except Exception:
        return None


def _profile_from_result(result: dict):
    return v9._profile_from_result(result)


def _profile_from_prior_intake(body):
    return v9._profile_from_prior_intake(body)


def _latest_user(body) -> str:
    return v9._latest_user(body)


def _hierarchical_brief(body) -> dict | None:
    if body is None:
        return None
    visible = list(getattr(body, "shown_cars", None) or [])
    if not visible:
        return None
    profile = _profile_from_prior_intake(body)
    if profile is None:
        return None
    brief = build_vehicle_brief(
        _latest_user(body),
        visible,
        profile,
        country=getattr(body, "country", None),
    )
    if not brief:
        return None
    return {
        "phase": "conversation",
        "reply": brief["reply"],
        "response_sections": brief["sections"],
        "verification_plan": brief["verification_plan"],
        "token_path": brief["token_path"],
        "advisor_mode": "verification_vehicle_brief",
        "llm_calls": 0,
    }


def _tighten_recommendations(result: Any) -> Any:
    """Reapply eligibility + an advisor floor after every older composition layer."""
    if not isinstance(result, dict) or result.get("phase") != "recommendation":
        return result
    profile = _profile_from_result(result)
    if profile is None:
        return result

    # One last authoritative quality pass. This intentionally protects Explore
    # too, because Explore is still a Carly surface, not a raw marketplace dump.
    combined = list(result.get("recommendations") or []) + list(result.get("explore") or [])
    eligible = filter_cards(combined, profile, limit=None)
    strong, rest = curate(eligible, profile, limit=MAX_STRONG, threshold=STRONG_THRESHOLD)
    explore = [card for card in rest if advisor_score(card, profile) >= EXPLORE_THRESHOLD][:MAX_EXPLORE]

    result["recommendations"] = strong
    result["explore"] = explore
    result["favorite"] = strong[0] if strong else None
    result["recommendation_count"] = len(strong)
    result["explore_count"] = len(explore)
    result["quality_candidate_count"] = len(strong) + len(explore)
    result["recommendation_quality_policy"] = "strong_threshold_plus_explore_floor"
    result["advisor_policy"] = {
        "token_cost": "zero_llm",
        "strong_threshold": STRONG_THRESHOLD,
        "explore_threshold": EXPLORE_THRESHOLD,
        "max_strong": MAX_STRONG,
        "max_explore": MAX_EXPLORE,
        "quality_over_scroll_depth": True,
    }

    if strong:
        top = strong[0]
        snap = top.get("advisor_snapshot") or {}
        name = " ".join(str(x) for x in (top.get("make"), top.get("model"), top.get("year")) if x)
        reason = "; ".join((snap.get("reasons") or [])[:2])
        result["reply"] = (
            f"Mi primera opción es el {name}"
            + (f": {reason}." if reason else ".")
            + f" Encontré {len(strong)} finalista{'s' if len(strong) != 1 else ''} que realmente mantendría"
            + (f" y {len(explore)} alternativa{'s' if len(explore) != 1 else ''} que todavía vale la pena explorar." if explore else ".")
        )

    decision = result.get("decision")
    if isinstance(decision, dict):
        decision["recommendations"] = list(strong)
        decision["explore"] = list(explore)
        decision["favorite"] = strong[0] if strong else None
        decision["advisor_policy"] = dict(result["advisor_policy"])
    return result


def _patch_v10_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue
        prior = endpoint

        def v10_endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = _request_body(args, kwargs)
            brief = _hierarchical_brief(body)
            if brief is not None:
                return brief
            result = __prior(*args, **kwargs)
            return _tighten_recommendations(result)

        route.endpoint = v10_endpoint
        dependant.call = v10_endpoint
        break


_patch_v10_route()
