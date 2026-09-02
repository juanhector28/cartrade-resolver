"""Carly v29: final eligibility hotfix for recommendation + explore.

Keeps v28 as the recommendation brain, then applies one final authoritative
eligibility gate to every surfaced card so Explore cannot bypass the same
mission constraints as the Top 3.
"""
from __future__ import annotations

import re
from typing import Any

from . import main_v28 as v28

app = v28.app

try:
    v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v29-final-eligibility"
except Exception:
    pass


def _body(card: dict) -> str:
    make = v28._norm(card.get("make"))
    model = v28._norm(card.get("model"))
    raw = v28._norm(card.get("body_type"))
    blob = f"{make} {model}"
    if v28._WORK_PICKUP_MODELS.search(blob):
        return "pickup"
    if re.search(r"\b(?:hfc|reward|npr|nqr|dutro|canter|elf|truck|camion)\b", blob, re.I):
        return "commercial"
    if raw in {"hatch", "hatchback"}:
        return "hatchback"
    return raw


def _eligible(card: dict, intent: dict[str, Any]) -> bool:
    if not isinstance(card, dict):
        return False
    body = _body(card)
    model = v28._norm(card.get("model"))

    # Daily university use should never surface work/commercial vehicles.
    if intent.get("student"):
        if body in {"pickup", "commercial", "van", "minivan"}:
            return False

    # Finca + heavy cargo needs actual load/rough-road capability.
    farm_heavy = intent.get("heavy_cargo") and (intent.get("farm") or intent.get("rough"))
    if farm_heavy and body not in {"pickup", "suv", "crossover"}:
        return False

    # Explicit comfort makes micro city cars fallback options, never preferred
    # over a viable compact/sedan/crossover set.
    if intent.get("student") and intent.get("comfort") and v28._MICRO_CITY_MODELS.search(model):
        return True

    return True


def _score(card: dict, intent: dict[str, Any]) -> float:
    score = float(card.get("advisor_score_v28") or v28._mission_score(card, intent, None))
    body = _body(card)
    model = v28._norm(card.get("model"))

    if intent.get("student") and intent.get("comfort"):
        if body == "sedan":
            score += 14.0
        elif body in {"crossover", "suv"}:
            score += 5.0
        if v28._CITY_COMFORT_MODELS.search(model):
            score += 7.0
        if v28._MICRO_CITY_MODELS.search(model):
            score -= 18.0
    return score


def _postfilter(body: Any, result: Any) -> Any:
    if not isinstance(result, dict) or result.get("phase") != "recommendation":
        return result

    intent = v28._intent(body)
    surfaced = list(result.get("recommendations") or []) + list(result.get("explore") or [])
    if not surfaced:
        return result

    eligible = [c for c in surfaced if _eligible(c, intent)]
    ranked = sorted(eligible, key=lambda c: _score(c, intent), reverse=True)

    # For student + comfort, keep micro city cars behind viable larger options.
    if intent.get("student") and intent.get("comfort"):
        non_micro = [c for c in ranked if not v28._MICRO_CITY_MODELS.search(v28._norm(c.get("model")))]
        micro = [c for c in ranked if c not in non_micro]
        if len(non_micro) >= 3:
            ranked = non_micro + micro

    top = ranked[:3]
    rest = ranked[3:12]

    labels = ["Mi favorita para tu caso", "Mi segunda opción", "La alternativa que mantendría"]
    if intent.get("student") and intent.get("comfort"):
        labels = ["Mejor equilibrio para universidad", "Más cómoda por tu dinero", "Alternativa práctica"]
    elif intent.get("farm") and intent.get("heavy_cargo"):
        labels = ["Mejor para finca y carga", "Mejor equilibrio trabajo/cuota", "Alternativa robusta"]

    for idx, card in enumerate(top):
        card["advisor_score_v29"] = round(_score(card, intent), 2)
        card["best_for"] = labels[idx]
        card["strategy_label"] = labels[idx]
        card["match_pct"] = max(70, min(96, round(_score(card, intent))))
        monthly = v28._num(card.get("monthly_est"))
        if monthly is not None and card.get("monthly_payment") is None:
            card["monthly_payment"] = monthly

    result["recommendations"] = top
    result["explore"] = rest
    result["favorite"] = top[0] if top else None
    result["recommendation_count"] = len(top)
    result["explore_count"] = len(rest)
    result["loaded_options"] = top + rest
    result["loaded_option_count"] = len(top) + len(rest)
    result["advisor_mode"] = "recommendation_brain_v29"
    result["final_eligibility_filtered_count"] = len(surfaced) - len(eligible)

    if intent.get("student") and intent.get("comfort"):
        result["reply"] = (
            "Para universidad prioricé comodidad diaria, tamaño manejable en ciudad y una cuota con margen. "
            "Las opciones están ordenadas por ajuste real a ese uso, no solo por ser las más baratas o nuevas."
        )
    elif intent.get("farm") and intent.get("heavy_cargo"):
        result["reply"] = (
            "Con grava, pasajeros y carga pesada, prioricé vehículos con capacidad real para ese trabajo y margen dentro de tu cuota."
        )

    brain = dict(result.get("recommendation_brain") or {})
    brain["version"] = "v29"
    brain["final_eligibility_filtered"] = len(surfaced) - len(eligible)
    result["recommendation_brain"] = brain

    decision = result.get("decision")
    if isinstance(decision, dict):
        decision["recommendations"] = list(top)
        decision["explore"] = list(rest)
        decision["favorite"] = result["favorite"]
    return result


def _patch_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None or getattr(prior, "_carly_v29_hotfix", False):
            continue

        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            try:
                commercial = v28.v27.v26.v25.v20.commercial
                body = commercial._request_body(args, kwargs)
            except Exception:
                body = None
            result = __prior(*args, **kwargs)
            return _postfilter(body, result)

        endpoint._carly_v29_hotfix = True
        route.endpoint = endpoint
        dependant.call = endpoint
        break


_patch_route()
