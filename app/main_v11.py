"""Carly v11 composition: authoritative fresh intake + consistent advisor briefs.

v11 targets live UI regressions without adding model spend:
- a fresh mission cannot coexist with a recommendation panel before budget exists
- focused vehicle enquiries stay on the hierarchical deterministic brief even when
  the frontend dropped part of the earlier intake history
- Explore is relative to the quality of the current finalists, not a fixed low bar
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from . import main_v10 as v10
from . import main_v7 as v7
from .carly_advisor import advisor_score, advisor_snapshot, semantic_class
from .carly_quality_gate import filter_cards
from .carly_vehicle_brief import build_vehicle_brief

app = v10.app
commercial = v10.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v11-state-brief-routing"

MAX_STRONG = 3
MAX_EXPLORE = 4
STRONG_THRESHOLD = 70.0
ABSOLUTE_EXPLORE_FLOOR = 64.0

_MONTHLY_RE = re.compile(r"\$?\s*(\d{2,4}(?:[.,]\d+)?)\s*(?:/\s*mes|al\s+mes|por\s+mes|mensuales?)", re.I)
_STANDALONE_MONTHLY_RE = re.compile(r"^\s*\$?\s*(\d{2,4}(?:[.,]\d+)?)\s*$", re.I)


def _request_body(args, kwargs):
    try:
        return commercial._request_body(args, kwargs)
    except Exception:
        return None


def _messages(body) -> list[Any]:
    return list(getattr(body, "messages", None) or []) if body is not None else []


def _infer_monthly_from_history(body) -> float | None:
    """Conservative fallback used only after a shortlist already exists."""
    values: list[float] = []
    for message in _messages(body):
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        if str(role or "").lower() != "user":
            continue
        raw = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
        text = v10.v9.v8._strip_frontend_context(raw)
        match = _MONTHLY_RE.search(text) or _STANDALONE_MONTHLY_RE.match(text)
        if not match:
            continue
        try:
            value = float(match.group(1).replace(",", "."))
        except ValueError:
            continue
        if 25 <= value < 2000:
            values.append(value)
    return values[-1] if values else None


def _fallback_visible_profile(body, visible: list[dict]):
    """Recover enough mission state for a zero-token brief when chat history is thin.

    We only infer city_runabout when the visible cards carry advisor metadata from
    Carly's own city curation. This avoids inventing a mission from arbitrary cars.
    """
    enriched = [c for c in visible if isinstance(c, dict) and (c.get("advisor_snapshot") or c.get("advisor_score") is not None)]
    if not enriched:
        return None
    cityish = sum(semantic_class(c) in {"city_hatch", "compact_hatch", "sedan"} for c in enriched)
    if cityish < max(1, (len(enriched) + 1) // 2):
        return None
    return SimpleNamespace(
        primary_job="city_runabout",
        max_monthly=_infer_monthly_from_history(body),
        prefer_body=["hatchback", "sedan"],
        require_body=[],
    )


def _profile_for_brief(body, visible: list[dict]):
    profile = v10._profile_from_prior_intake(body)
    return profile or _fallback_visible_profile(body, visible)


def _hierarchical_brief(body) -> dict | None:
    if body is None:
        return None
    visible = list(getattr(body, "shown_cars", None) or [])
    if not visible:
        return None
    profile = _profile_for_brief(body, visible)
    if profile is None:
        return None
    brief = build_vehicle_brief(
        v10._latest_user(body), visible, profile, country=getattr(body, "country", None)
    )
    if not brief:
        return None
    return {
        "phase": "conversation",
        "reply": brief["reply"],
        "response_sections": brief["sections"],
        "render_hint": "sectioned_advisor_brief",
        "verification_plan": brief["verification_plan"],
        "token_path": brief["token_path"],
        "advisor_mode": "verification_vehicle_brief_v11",
        "llm_calls": 0,
        "clear_recommendations": False,
    }


def _fresh_intake_response(body) -> dict | None:
    """Outermost P0: no cards are valid before a fresh mission has enough intake."""
    if body is None:
        return None
    rows = _messages(body)
    country = getattr(body, "country", None)
    if not v7._is_high_confidence_intake_turn(rows, country=country):
        return None
    blocker = commercial.preview.deterministic_intake_reply(rows, country=country)
    if not blocker:
        return None
    # This is intentionally explicit. The frontend already has a clear/replace
    # contract; a fresh intake must wipe any preloaded or stale recommendation UI.
    return {
        "phase": "conversation",
        "reply": blocker,
        "token_path": "deterministic_fresh_intake",
        "llm_calls": 0,
        "clear_recommendations": True,
        "replace_recommendations": True,
        "recommendations": [],
        "explore": [],
        "favorite": None,
        "recommendation_count": 0,
        "explore_count": 0,
        "ui_state": "fresh_intake_empty",
        "show_market_animation": False,
        "market_search_performed": False,
    }


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _refined_score(card: dict, profile: Any) -> float:
    """Small deterministic tie-breaker over v9 mission score, never novelty noise."""
    score = advisor_score(card, profile)
    quality = _num(card.get("quality_score"))
    if quality is None:
        quality = _num(card.get("listing_quality"))
    if quality is not None:
        if quality >= 80: score += 4
        elif quality >= 65: score += 2
        elif quality < 55: score -= 5

    if getattr(profile, "primary_job", None) == "city_runabout":
        cls = semantic_class(card)
        if cls == "city_hatch": score += 3
        elif cls == "compact_hatch": score += 1
        elif cls == "sedan": score -= 3

    risk = _num(card.get("visible_damage_risk"))
    if risk is not None and risk > 0.20:
        score -= min(5.0, risk * 10.0)
    return round(max(0.0, min(100.0, score)), 1)


def _decorate(card: dict, profile: Any, rank: int | None, score: float) -> dict:
    out = dict(card)
    snap = advisor_snapshot(out, profile, rank)
    snap["score"] = score
    out["advisor_snapshot"] = snap
    out["advisor_score"] = score
    if rank:
        out["best_for"] = snap["label"]
        out["strategy_label"] = snap["label"]
        out["advisor_reason"] = "; ".join((snap.get("reasons") or [])[:2])
        out["advisor_tradeoff"] = (snap.get("tradeoffs") or [""])[0]
    return out


def _tighten_result(result: Any) -> Any:
    if not isinstance(result, dict) or result.get("phase") != "recommendation":
        return result
    profile = v10._profile_from_result(result)
    if profile is None:
        return result

    combined = list(result.get("recommendations") or []) + list(result.get("explore") or [])
    eligible = filter_cards(combined, profile, limit=None)
    unique: list[dict] = []
    seen = set()
    for card in eligible:
        key = card.get("url") or card.get("id") or (card.get("make"), card.get("model"), card.get("year"), card.get("price_usd"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(card)

    ranked = sorted(unique, key=lambda c: _refined_score(c, profile), reverse=True)
    strong_raw = [c for c in ranked if _refined_score(c, profile) >= STRONG_THRESHOLD][:MAX_STRONG]
    if not strong_raw and ranked and _refined_score(ranked[0], profile) >= 60:
        strong_raw = ranked[:1]
    strong_keys = {c.get("url") or c.get("id") or (c.get("make"), c.get("model"), c.get("year"), c.get("price_usd")) for c in strong_raw}

    top_score = _refined_score(strong_raw[0], profile) if strong_raw else (_refined_score(ranked[0], profile) if ranked else 0)
    explore_floor = max(ABSOLUTE_EXPLORE_FLOOR, top_score - 18.0)
    rest = [c for c in ranked if (c.get("url") or c.get("id") or (c.get("make"), c.get("model"), c.get("year"), c.get("price_usd"))) not in strong_keys]
    explore_raw = [c for c in rest if _refined_score(c, profile) >= explore_floor][:MAX_EXPLORE]

    strong = [_decorate(c, profile, idx, _refined_score(c, profile)) for idx, c in enumerate(strong_raw, 1)]
    explore = [_decorate(c, profile, None, _refined_score(c, profile)) for c in explore_raw]
    result["recommendations"] = strong
    result["explore"] = explore
    result["favorite"] = strong[0] if strong else None
    result["recommendation_count"] = len(strong)
    result["explore_count"] = len(explore)
    result["quality_candidate_count"] = len(strong) + len(explore)
    result["recommendation_quality_policy"] = "relative_quality_floor"
    result["advisor_policy"] = {
        "token_cost": "zero_llm",
        "max_strong": MAX_STRONG,
        "max_explore": MAX_EXPLORE,
        "strong_threshold": STRONG_THRESHOLD,
        "explore_floor": explore_floor,
        "stable_over_novel": True,
    }
    decision = result.get("decision")
    if isinstance(decision, dict):
        decision["recommendations"] = list(strong)
        decision["explore"] = list(explore)
        decision["favorite"] = strong[0] if strong else None
        decision["advisor_policy"] = dict(result["advisor_policy"])
    return result


def _patch_v11_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue
        prior = endpoint

        def v11_endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = _request_body(args, kwargs)
            fresh = _fresh_intake_response(body)
            if fresh is not None:
                return fresh
            brief = _hierarchical_brief(body)
            if brief is not None:
                return brief
            result = __prior(*args, **kwargs)
            return _tighten_result(result)

        route.endpoint = v11_endpoint
        dependant.call = v11_endpoint
        break


_patch_v11_route()
