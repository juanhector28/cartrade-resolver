"""Production preview-first layer for Carly.

Sits above the Decision Room. Common intake journeys are resolved with rules and
structured state first; the LLM is reserved for ambiguous language.
"""
from __future__ import annotations

from typing import Any

from . import main_room as room
from .carly_fastpath import deterministic_intake_reply, extract_fast_profile
from .carly_preview_first import preview_policy

app = room.app
legacy = room.legacy
guarded = room.guarded


PREVIEW_FIRST_PROMPT = r"""

# PREVIEW FIRST
Muestra mercado pronto. Si ya entiendes uso/intencion y existe presupuesto o
capacidad de pago, emite <PROFILE> y recomienda. No preguntes marca, transmision,
carroceria secundaria, plazo ni prioridades blandas solo para completar perfil.
Nunca hagas una cuarta pregunta antes del primer preview.
"""

# Small extraction-only prompt used only when the deterministic parser cannot
# safely classify a journey. This replaces resending Carly's full advisory prompt
# for a mechanical JSON extraction task.
_COMPACT_PROFILE_PROMPT = r"""
Eres el extractor de estado de Carly. Devuelve SOLO <PROFILE>{json}</PROFILE>.
No converses. No inventes datos. Desconocido = null o lista vacia.

Campos:
country, target_monthly, max_monthly, target_price, max_price, min_year,
primary_job, secondary_job, usage, daily_km, passengers, small_children,
road_mix, cargo_level, holding_period, cost_sensitivity, priority, secondary,
avoid_body, require_body, prefer_body, intent_segment, avoid_transmission,
avoid_brands, prefer_brands, require_brands, open_to_surprise.

primary_job/secondary_job solo: daily_commute, family_transport, first_car,
work_vehicle, delivery, long_distance, city_runabout, upgrade,
status_lifestyle, weekend_adventure, rideshare.

Reglas: una cuota declarada como maximo/techo -> max_monthly. Un precio total
maximo -> max_price. Una prima NO es presupuesto. "solo/tiene que ser" = hard;
"me gusta/preferiria" = preferencia. No emitas pesos ni ideal_vector.
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


def _compact_messages(messages, keep: int = 6):
    rows = list(messages or [])
    return rows[-keep:] if len(rows) > keep else rows


def _profile_extraction(body) -> dict | None:
    """Extract profile with rules first, one compact LLM call only if needed."""
    if body is None:
        return None
    country = getattr(body, "country", None)
    messages = list(getattr(body, "messages", None) or [])

    fast = extract_fast_profile(messages, country=country)
    if fast:
        return fast

    if not legacy._anthropic:
        return None
    msgs, frontend_meta = guarded._clean_frontend_context_guarded(_compact_messages(messages))
    system = _COMPACT_PROFILE_PROMPT
    if country:
        system += f"\nPais confirmado por sistema: {str(country).lower().strip()}."
    if frontend_meta:
        system += "\n" + "\n".join(frontend_meta[-3:])

    try:
        resp = legacy._anthropic.messages.create(
            model=legacy.CARLY_MODEL,
            max_tokens=450,
            system=system,
            messages=msgs,
        )
    except Exception:
        legacy.log.exception("Carly compact profile extraction failed")
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


def _preview_result(body, policy: dict, data: dict | None = None) -> dict | None:
    data = data or _profile_extraction(body)
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
            + (f"Con lo que sé hasta ahora, empezaría por el {name}. " if name else "")
            + "Te muestro solo las opciones que pasan mi filtro y afinamos desde ahí."
        )
    else:
        reply = (
            "Ya tengo suficiente para revisar el mercado. No encontré un match exacto "
            "con estos criterios; podemos afinar sin reiniciar la búsqueda."
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
        "token_path": "deterministic" if extract_fast_profile(list(getattr(body, "messages", None) or []), country=getattr(body, "country", None)) else "compact_extraction",
    }
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

            # Zero-token path: common request already contains a clear job + budget.
            # Rank immediately instead of asking the conversational LLM to emit the
            # same structured profile first.
            if body is not None and not visible:
                fast = extract_fast_profile(messages, country=getattr(body, "country", None))
                if fast:
                    direct = _preview_result(body, {**policy, "reason": "deterministic_fastpath"}, data=fast)
                    if direct is not None:
                        return direct

                # Common missing-blocker questions do not require generative AI.
                blocker = deterministic_intake_reply(messages, country=getattr(body, "country", None))
                if blocker and not policy.get("force_preview"):
                    return {
                        "phase": "conversation",
                        "reply": blocker,
                        "token_path": "deterministic",
                    }

                # If the question cap is already reached, do not pay for the normal
                # conversational call and then pay again for forced extraction.
                if policy.get("force_preview"):
                    forced = _preview_result(body, policy)
                    if forced is not None:
                        return forced

            result = __prior(*args, **kwargs)
            return _mark_first_preview(result, body, policy)

        route.endpoint = preview_endpoint
        dependant.call = preview_endpoint
        break


_patch_preview_route()
