"""Production conversation-state layer for Carly.

This sits above main_decision. It invalidates stale recommendation cards when the
buyer explicitly changes missions, so an old shortlist cannot keep steering a new
decision. The API also emits an explicit UI contract to clear/replace old cards.
"""
from __future__ import annotations

from typing import Any

from . import main_decision as decision
from .carly_state import has_unresolved_decision_reset

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
        # A fresh shortlist was produced during this very turn. The frontend must
        # atomically replace the previous cards/CTA with this new decision set.
        result["decision_state"] = "active"
        result["replace_recommendations"] = True
        result["clear_recommendations"] = False
        return result

    # The new profile is still being built. Old cards are now historical only.
    result["decision_state"] = "rebuilding"
    result["clear_recommendations"] = True
    result["replace_recommendations"] = False
    result["recommendations"] = []
    result["explore"] = []
    result["favorite"] = None
    return result


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

            # Crucial invariant: a previous shortlist cannot be fed back into Carly
            # while she is building a materially different buyer profile.
            if reset_pending:
                _drop_stale_cards(body)

            result = __prior(*args, **kwargs)
            return _apply_decision_state(result, reset_pending)

        route.endpoint = state_endpoint
        dependant.call = state_endpoint
        break


_patch_state_route()
