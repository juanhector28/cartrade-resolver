"""Production Decision Room layer for Carly.

Sits above main_state and turns every material recommendation into a durable
Decision payload. It also exposes a deterministic market-refresh endpoint so a
saved decision can be re-ranked against current inventory without replaying the
conversation through the LLM.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from . import main_state as state
from .carly_decision_room import build_decision, compare_decisions, decorate_response

app = state.app
legacy = state.legacy
guarded = state.guarded


DECISIVE_PROMPT = r"""

# CARLY COMO DECISION MAKER
Tu valor no es describir opciones: es reducir trabajo cognitivo. Cuando el usuario
pregunte cual escogerias, cual comprarias, por donde empezarias, pros/contras o si
vale la pena una unidad, abre con un VEREDICTO claro y luego justificalo.

Formato mental:
1) Veredicto: una unidad concreta, o "ninguna por ahora".
2) Dos razones ligadas al comprador y a datos disponibles.
3) Que falta verificar o que podria hacerte cambiar de opinion.

Puedes decir "yo no compraria ninguno de estos" cuando los datos no justifican
avanzar. No confundas firmeza con certeza: nunca inventes estado, historial,
especificaciones ni confiabilidad de una unidad concreta.
"""

# Both initial discovery and post-shortlist follow-ups inherit the rule. Guard
# against module reloads duplicating the prompt.
try:
    if DECISIVE_PROMPT.strip() not in str(legacy.CARLY_SYSTEM_PROMPT):
        legacy.CARLY_SYSTEM_PROMPT += DECISIVE_PROMPT
except Exception:
    pass
try:
    if DECISIVE_PROMPT.strip() not in str(guarded._FOLLOWUP_SYSTEM_PROMPT):
        guarded._FOLLOWUP_SYSTEM_PROMPT += DECISIVE_PROMPT
except Exception:
    pass


def _request_body(args, kwargs):
    try:
        return guarded._request_body(args, kwargs)
    except Exception:
        return None


def _patch_decision_room_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue

        prior = endpoint

        def room_endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = _request_body(args, kwargs)
            result = __prior(*args, **kwargs)
            country = getattr(body, "country", None) if body is not None else None
            return decorate_response(result, country=country)

        route.endpoint = room_endpoint
        dependant.call = room_endpoint
        break


class DecisionRefreshRequest(BaseModel):
    decision: dict
    country: Optional[str] = None
    top_n: int = 6


def _profile_from_decision(decision: dict):
    data = dict(decision.get("profile") or {})
    # profile_from_extraction is already patched by main_guarded, so the same
    # deterministic Need Vector + hard filters used in normal Carly apply here.
    return legacy.profile_from_extraction(data)


def _explore_cards(pool: list[dict], cards: list[dict], limit: int = 24) -> list[dict]:
    curated = {c.get("url") for c in cards if c.get("url")}
    fields = (
        "id", "country", "url", "make", "model", "year", "km", "price_usd",
        "monthly_est", "transmission", "location", "body_type", "primary_photo",
        "quality_score",
    )
    out = []
    for row in pool:
        if row.get("url") in curated:
            continue
        out.append({k: row.get(k) for k in fields})
        if len(out) >= limit:
            break
    return out


@app.post("/carly/decision/refresh")
def refresh_decision(body: DecisionRefreshRequest):
    """Re-rank one saved Decision against the current inventory snapshot.

    This is the first Market Watch primitive. No LLM call is required, so it is
    cheap enough for foreground refreshes and future scheduled monitoring.
    """
    previous = dict(body.decision or {})
    profile = _profile_from_decision(previous)
    country = (body.country or previous.get("country") or (previous.get("profile") or {}).get("country"))
    if isinstance(country, str):
        country = country.lower().strip() or None

    pool = legacy._carly_inventory(profile, country=country)
    curated_n = max(3, min(int(body.top_n or 6), 6))
    top = legacy.rank_cars(pool, profile, top_n=curated_n)
    cards = [legacy._carly_card(entry) for entry in top]
    result = {
        "phase": "recommendation",
        "profile": dict(previous.get("profile") or {}),
        "pool_size": len(pool),
        "recommendations": cards,
        "explore": _explore_cards(pool, cards),
        "show_market_animation": True,
        "replace_recommendations": True,
        "clear_recommendations": False,
    }
    current = build_decision(result, country=country)
    current["market_watch"]["enabled"] = bool((previous.get("market_watch") or {}).get("enabled"))
    changes = compare_decisions(previous, current)
    result["decision"] = current
    result["decision_room"] = True
    result["market_changes"] = changes
    if changes:
        result["market_watch_summary"] = changes[0]["message"]
    else:
        result["market_watch_summary"] = "Tu shortlist sigue estable con el mercado actual."
    return result


_patch_decision_room_route()
