"""Production preview-first layer for Carly.

Sits above the Decision Room. Carly should earn the right to keep asking by
showing useful market value first: target <=2 questions before the first preview,
third only for a genuine blocker, and never a fourth pre-preview question.
"""
from __future__ import annotations

import re
from typing import Any

from . import main_room as room
from .carly_preview_first import preview_policy

app = room.app
legacy = room.legacy
guarded = room.guarded


PREVIEW_FIRST_PROMPT = r"""

# PREVIEW FIRST: REGLA DE TIME-TO-VALUE
Tu objetivo no es completar un perfil perfecto antes de enseñar mercado. Tu
objetivo es darle valor al comprador lo antes posible y refinar DESPUES de que
ya tenga carros reales enfrente.

Reglas obligatorias antes del primer shortlist:
1) Aspira a mostrar una primera ronda tras 0-2 preguntas útiles.
2) Si ya conoces una intención/uso razonable Y algún límite de presupuesto o
   capacidad de pago, EMITE <PROFILE> y recomienda ahora. Lo desconocido queda
   como null o preferencia pendiente; no bloquea el preview.
3) Una tercera pregunta solo se permite si todavía falta UNO de estos dos
   bloques materiales: (a) intención/uso suficientemente entendible, o (b) una
   referencia de presupuesto/capacidad de pago.
4) NUNCA hagas una cuarta pregunta antes de mostrar mercado. Después de tres
   preguntas, emite el mejor <PROFILE> provisional posible con lo que sabes y
   muestra una primera ronda, aunque queden preferencias por afinar.
5) Marca, transmisión, carrocería secundaria, plazo financiero, prioridad
   declarada y detalles blandos NO bloquean el primer preview salvo que el
   comprador los haya expresado como requisito duro.
6) Si la persona pide un modelo concreto, no uses preguntas de estilo de vida
   para retrasar el preview. Primero enseña mercado relevante; luego afina si
   hace falta.
7) El primer shortlist es una hipótesis útil, no una sentencia final. Después de
   mostrarlo puedes seguir aprendiendo y reordenar con cada dato nuevo.

Patrón de producto: understand enough -> preview -> learn -> rerank -> decide.
"""

_FORCE_PROFILE_PROMPT = r"""

# FORZAR PREVIEW AHORA
El límite de preguntas pre-preview ya se alcanzó o ya existe información
suficiente. NO hagas otra pregunta. Extrae el mejor perfil provisional posible
solo con hechos explícitos/inferencias permitidas por Carly. Campos desconocidos
quedan null o vacíos. No inventes presupuesto, pasajeros, kilometraje, plazo ni
preferencias.

Devuelve SOLO un bloque <PROFILE> válido según el esquema de Carly. No agregues
prosa antes ni después. Si hay país confirmado por sistema, úsalo. Si el usuario
dio una cuota máxima, guárdala como max_monthly; si dio precio total máximo,
max_price. Una prima/enganche por sí sola NO es precio total máximo.
"""

try:
    if PREVIEW_FIRST_PROMPT.strip() not in str(legacy.CARLY_SYSTEM_PROMPT):
        legacy.CARLY_SYSTEM_PROMPT += PREVIEW_FIRST_PROMPT
except Exception:
    pass


def _request_body(args, kwargs):
    try:
        return guarded._request_body(args, kwargs)
    except Exception:
        return None


def _profile_extraction(body) -> dict | None:
    if body is None or not legacy._anthropic:
        return None
    msgs, frontend_meta = guarded._clean_frontend_context_guarded(body.messages)
    system = legacy.CARLY_SYSTEM_PROMPT + _FORCE_PROFILE_PROMPT
    country = getattr(body, "country", None)
    if country:
        system += (
            "\n\n# CONTEXTO CONFIRMADO POR EL SISTEMA\n"
            f"Pais/codigo seleccionado: {country}. No lo vuelvas a preguntar."
        )
    if frontend_meta:
        system += "\n" + "\n".join(frontend_meta)

    try:
        resp = legacy._anthropic.messages.create(
            model=legacy.CARLY_MODEL,
            max_tokens=1000,
            system=system,
            messages=msgs,
        )
    except Exception:
        legacy.log.exception("Carly preview-first forced extraction failed")
        return None

    raw = "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    ).strip()
    data = legacy.extract_profile_json(raw)
    if not isinstance(data, dict):
        return None
    if country and not data.get("country"):
        data["country"] = str(country).lower().strip()
    return data


def _preview_result(body, policy: dict) -> dict | None:
    data = _profile_extraction(body)
    if not data:
        return None
    try:
        profile = legacy.profile_from_extraction(data)
        chat_country = data.get("country") if isinstance(data, dict) else None
        country = chat_country or getattr(body, "country", None) or None
        if isinstance(country, str):
            country = country.lower().strip() or None
        pool = legacy._carly_inventory(profile, country=country)
        curated_n = max(3, min(int(getattr(body, "top_n", 6) or 6), 6))
        top = legacy.rank_cars(pool, profile, top_n=curated_n)
        cards = [legacy._carly_card(entry) for entry in top]
    except Exception:
        legacy.log.exception("Carly preview-first ranking failed")
        return None

    if cards:
        top_car = cards[0]
        name = " ".join(
            str(top_car.get(k)) for k in ("make", "model", "year") if top_car.get(k)
        ).strip()
        reply = (
            "Ya tengo suficiente para darte una primera ronda. "
            + (f"Con lo que sé hasta ahora, empezaría mirando el {name}. " if name else "")
            + "Te muestro mis mejores opciones y afinamos el ranking mientras las ves."
        )
    else:
        reply = (
            "Ya tengo suficiente para revisar el mercado sin seguir interrogándote. "
            "No encontré un match exacto con lo que sé hasta ahora; podemos afinar desde "
            "aquí sin reiniciar la búsqueda."
        )

    result = {
        "phase": "recommendation",
        "reply": reply,
        "profile": data,
        "pool_size": len(pool),
        "recommendations": cards,
        "explore": room._explore_cards(pool, cards),
        "favorite": cards[0] if cards else None,
        "recommendation_stage": "preview",
        "preview": True,
        "preview_reason": policy.get("reason"),
        "preview_question_count": int(policy.get("questions") or 0),
        "refinement_available": True,
        "show_market_animation": True,
        "replace_recommendations": True,
        "clear_recommendations": False,
    }
    # Preserve the same frontend state contract emitted by main_state.
    result = room.state.apply_ui_contract(result)
    return room.decorate_response(result, country=country)


def _mark_first_preview(result: Any, body, policy: dict) -> Any:
    if not isinstance(result, dict) or result.get("phase") != "recommendation":
        return result
    if body is not None and (getattr(body, "shown_cars", None) or []):
        return result
    result.setdefault("recommendation_stage", "preview")
    result.setdefault("preview", True)
    result.setdefault("preview_question_count", int(policy.get("questions") or 0))
    result.setdefault("refinement_available", True)
    decision = result.get("decision")
    if isinstance(decision, dict):
        decision["stage"] = "preview"
        decision["refinement"] = {
            "available": True,
            "message": "Puedes seguir afinando mientras ya ves el mercado.",
        }
    return result


def _patch_preview_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue
        prior = endpoint

        def preview_endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = _request_body(args, kwargs)
            messages = list(getattr(body, "messages", None) or []) if body is not None else []
            visible = bool(getattr(body, "shown_cars", None) or []) if body is not None else False
            policy = preview_policy(messages, has_visible_cars=visible)

            result = __prior(*args, **kwargs)
            # The prompt should normally cause Carly to preview on her own. This
            # runtime fallback makes the question cap an invariant, not a request.
            if (
                isinstance(result, dict)
                and result.get("phase") == "conversation"
                and policy.get("force_preview")
                and not visible
            ):
                forced = _preview_result(body, policy)
                if forced is not None:
                    return forced
            return _mark_first_preview(result, body, policy)

        route.endpoint = preview_endpoint
        dependant.call = preview_endpoint
        break


_patch_preview_route()
