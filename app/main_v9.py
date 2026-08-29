"""Carly v9 composition: zero-token recommendation intelligence.

v9 leaves the now-stable intake path alone. It post-processes already quality-
gated candidates into a mission-relative shortlist and intercepts common vehicle
enquiries with deterministic comparative advice before any LLM route.
"""
from __future__ import annotations

from typing import Any

from . import main_v8 as v8
from .carly_advisor import curate, rich_followup

app = v8.app
commercial = v8.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v9-advisor-intelligence"


def _request_body(args, kwargs):
    try:
        return commercial._request_body(args, kwargs)
    except Exception:
        return None


def _profile_from_result(result: dict):
    data = result.get("profile")
    if not isinstance(data, dict):
        return None
    try:
        return commercial.legacy.profile_from_extraction(dict(data))
    except Exception:
        return None


def _profile_from_prior_intake(body):
    """Recover buyer mission deterministically for follow-ups, never via LLM."""
    if body is None:
        return None
    messages = list(getattr(body, "messages", None) or [])
    country = getattr(body, "country", None)
    # The latest user turn can name a model, which intentionally makes the fast
    # profile parser fall back. The prior intake is enough for the buyer mission.
    candidates = [messages[:-1], messages]
    for rows in candidates:
        data = v8.fastpath.extract_fast_profile(rows, country=country)
        if not data:
            continue
        try:
            return commercial.legacy.profile_from_extraction(dict(data))
        except Exception:
            continue
    return None


def _latest_user(body) -> str:
    for message in reversed(list(getattr(body, "messages", None) or [])):
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        if str(role or "").lower() == "user":
            content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
            return v8._strip_frontend_context(content)
    return ""


def _advisor_followup(body) -> dict | None:
    visible = list(getattr(body, "shown_cars", None) or []) if body is not None else []
    if not visible:
        return None
    profile = _profile_from_prior_intake(body)
    if profile is None:
        return None
    latest = _latest_user(body)
    reply = rich_followup(latest, visible, profile)
    if not reply:
        return None
    return {
        "phase": "conversation",
        "reply": reply,
        "token_path": "deterministic_advisor",
        "advisor_mode": "comparative_brief",
        "llm_calls": 0,
    }


def _curate_result(result: Any) -> Any:
    if not isinstance(result, dict) or result.get("phase") != "recommendation":
        return result
    profile = _profile_from_result(result)
    if profile is None or getattr(profile, "primary_job", None) != "city_runabout":
        return result

    candidates = list(result.get("recommendations") or []) + list(result.get("explore") or [])
    strong, rest = curate(candidates, profile, limit=3, threshold=58.0)
    result["recommendations"] = strong
    result["explore"] = rest[:12]
    result["favorite"] = strong[0] if strong else None
    result["recommendation_count"] = len(strong)
    result["recommendation_quality_policy"] = "advisor_threshold_not_quota"
    result["advisor_policy"] = {
        "token_cost": "zero_llm",
        "strong_threshold": 58.0,
        "max_strong": 3,
        "mission_relative": True,
    }

    if strong:
        top = strong[0]
        snap = top.get("advisor_snapshot") or {}
        name = " ".join(str(x) for x in (top.get("make"), top.get("model"), top.get("year")) if x)
        why = "; ".join((snap.get("reasons") or [])[:2])
        result["reply"] = (
            f"Ya comparé las opciones que pasan el filtro. Yo empezaría por el {name}"
            + (f" porque {why}." if why else ".")
            + " Te dejo solo las que realmente mantendría como finalistas; el resto queda como exploración."
        )

    decision = result.get("decision")
    if isinstance(decision, dict):
        decision["recommendations"] = list(strong)
        decision["explore"] = list(result["explore"])
        decision["favorite"] = strong[0] if strong else None
        decision["advisor_policy"] = dict(result["advisor_policy"])
    return result


def _patch_v9_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue
        prior = endpoint

        def v9_endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = _request_body(args, kwargs)
            direct = _advisor_followup(body)
            if direct is not None:
                return direct
            result = __prior(*args, **kwargs)
            return _curate_result(result)

        route.endpoint = v9_endpoint
        dependant.call = v9_endpoint
        break


_patch_v9_route()
