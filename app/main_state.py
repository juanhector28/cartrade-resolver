"""Production conversation-state layer for Carly.

This sits above main_decision. It invalidates stale recommendation cards when the
buyer explicitly changes missions, emits an explicit UI contract for market-search
animations, and repairs missing context when a buyer asks about an explore card
that the frontend failed to echo back in ``shown_cars``.
"""
from __future__ import annotations

from typing import Any

from . import main_decision as decision
from .carly_state import has_unresolved_decision_reset
from .carly_ui_contract import apply_ui_contract, message_names_car, norm_text, phrase_in, requested_year

app = decision.app
guarded = decision.guarded
legacy = decision.legacy


def _body_messages(body) -> list[Any]:
    return list(getattr(body, "messages", None) or []) if body is not None else []


def _drop_stale_cards(body) -> None:
    if body is None:
        return
    try:
        body.shown_cars = None
    except Exception:
        pass


def _apply_decision_state(result: Any, reset_pending: bool) -> Any:
    if not isinstance(result, dict) or not reset_pending:
        return result

    if result.get("phase") == "recommendation" and result.get("recommendations"):
        result["decision_state"] = "active"
        result["replace_recommendations"] = True
        result["clear_recommendations"] = False
        return result

    result["decision_state"] = "rebuilding"
    result["clear_recommendations"] = True
    result["replace_recommendations"] = False
    result["recommendations"] = []
    result["explore"] = []
    result["favorite"] = None
    return result


def _latest_text(body) -> str:
    try:
        return guarded._latest_user_text(body)
    except Exception:
        return ""


def _visible_already_contains_named_car(body, latest: str) -> bool:
    for car in list(getattr(body, "shown_cars", None) or []):
        if isinstance(car, dict) and message_names_car(latest, car):
            return True
    return False


def _inventory_lookup_for_named_car(body) -> dict | None:
    """Best-effort rescue for explore cards omitted from shown_cars by the UI.

    This only runs on post-shortlist turns, only when the buyer names a model +
    year, and returns the highest-quality exact model/year inventory match. It is
    a safety net, not a replacement for the frontend sending every visible card.
    """
    if body is None or not legacy.supabase:
        return None
    current = list(getattr(body, "shown_cars", None) or [])
    if not current:
        return None

    latest = _latest_text(body)
    year = requested_year(latest)
    if not latest or year is None or _visible_already_contains_named_car(body, latest):
        return None

    fields = (
        "id,country,url,make,model,year,km,price_usd,monthly_est,transmission,"
        "location,body_type,primary_photo,quality_score"
    )
    try:
        q = (
            legacy.supabase.table("scraped_listings")
            .select(fields)
            .eq("status", "staging")
            .eq("year", year)
            .order("quality_score", desc=True)
            .limit(150)
        )
        country = getattr(body, "country", None)
        if isinstance(country, str) and country.strip():
            q = q.eq("country", country.lower().strip())
        rows = q.execute().data or []
    except Exception:
        legacy.log.exception("Carly named explore-card lookup failed")
        return None

    text_n = norm_text(latest)
    ranked: list[tuple[int, dict]] = []
    for row in rows:
        model = row.get("model")
        if not model or not phrase_in(text_n, model):
            continue
        score = 2
        make = row.get("make")
        if make and phrase_in(text_n, make):
            score += 2
        if str(row.get("year") or "") == str(year):
            score += 2
        ranked.append((score, row))

    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _augment_missing_visible_card(body) -> bool:
    """Inject one resolved inventory card so follow-up grounding can discuss it."""
    car = _inventory_lookup_for_named_car(body)
    if not car:
        return False
    try:
        cards = list(getattr(body, "shown_cars", None) or [])
        keys = {(c.get("url"), c.get("id")) for c in cards if isinstance(c, dict)}
        key = (car.get("url"), car.get("id"))
        if key not in keys:
            cards.append(car)
        body.shown_cars = cards[-12:]
        return True
    except Exception:
        return False


def _patch_state_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue

        prior_endpoint = endpoint

        def state_endpoint(*args: Any, __prior=prior_endpoint, **kwargs: Any):
            body = guarded._request_body(args, kwargs)
            reset_pending = has_unresolved_decision_reset(_body_messages(body))

            if reset_pending:
                _drop_stale_cards(body)
            else:
                # "Ver otros 6" safety net: if the UI forgot to echo a newly
                # visible explore card, resolve the named real unit before Carly
                # answers instead of falsely claiming she has no data for it.
                _augment_missing_visible_card(body)

            result = __prior(*args, **kwargs)
            result = _apply_decision_state(result, reset_pending)
            return apply_ui_contract(result)

        route.endpoint = state_endpoint
        dependant.call = state_endpoint
        break


_patch_state_route()
