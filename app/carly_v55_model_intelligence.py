"""Carly v55: keep model questions out of unit-assessment fastpaths.

A buyer asking for pros/cons, reliability or known issues of a model is asking at
model scope. That intent must be resolved before the deterministic unit brief,
otherwise Carly can answer with listing price/km/VIN language instead of actual
model intelligence.

The web client appends a hidden CarTrade context block to the latest user turn.
Routing must classify the buyer's visible text, not that metadata. v55 therefore
strips the context block and invokes the compact follow-up path with a sanitized
copy of the request.
"""
from __future__ import annotations

import copy
import logging
from functools import wraps
from typing import Any

from . import carly_v52_hotfix as v52
from . import main_v50 as v50

log = logging.getLogger("carly.v55")

_CONTEXT_MARKER = "[CONTEXTO ACTIVO DE CARTRADE:"


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _buyer_text(value: Any) -> str:
    text = str(value or "")
    idx = text.find(_CONTEXT_MARKER)
    if idx >= 0:
        text = text[:idx]
    return text.strip()


def _latest_buyer_text(body: Any) -> str:
    messages = list(_get(body, "messages", []) or [])
    for message in reversed(messages):
        if str(_get(message, "role", "") or "").lower() == "user":
            return _buyer_text(_get(message, "content", ""))
    return ""


def _is_model_intelligence(body: Any) -> bool:
    shown = list(_get(body, "shown_cars", []) or [])
    latest = _latest_buyer_text(body)
    return bool(shown and latest and v52._is_model_intelligence(latest))


def _sanitized_body(body: Any) -> Any:
    """Copy a request and remove frontend routing metadata from its latest user turn."""
    if body is None:
        return None
    messages = list(_get(body, "messages", []) or [])
    clean_messages: list[Any] = []
    latest_user_idx = -1
    for i, message in enumerate(messages):
        if str(_get(message, "role", "") or "").lower() == "user":
            latest_user_idx = i
    for i, message in enumerate(messages):
        if isinstance(message, dict):
            cloned = dict(message)
            if i == latest_user_idx:
                cloned["content"] = _buyer_text(cloned.get("content"))
        else:
            try:
                cloned = copy.copy(message)
                if i == latest_user_idx:
                    setattr(cloned, "content", _buyer_text(getattr(cloned, "content", "")))
            except Exception:
                cloned = message
        clean_messages.append(cloned)

    if isinstance(body, dict):
        clean = dict(body)
        clean["messages"] = clean_messages
        return clean
    try:
        clean = copy.copy(body)
        setattr(clean, "messages", clean_messages)
        return clean
    except Exception:
        return body


def _model_intelligence_response(body: Any) -> dict | None:
    if not _is_model_intelligence(body):
        return None
    clean = _sanitized_body(body)
    try:
        decision = v50.v47.commercial.preview.room.state.decision
        direct = decision._answer_followup_integrity(clean)
    except Exception:
        log.exception("Carly v55 model-intelligence path failed")
        return None
    if not isinstance(direct, dict):
        return None
    direct["route_precedence"] = "model_intelligence_v55"
    direct["model_scope"] = True
    return direct


def install(app: Any) -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None or getattr(prior, "_carly_v55_model_intelligence", False):
            continue

        @wraps(prior)
        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = v50.v47.commercial._request_body(args, kwargs)
            direct = _model_intelligence_response(body)
            if direct is not None:
                return direct
            return __prior(*args, **kwargs)

        endpoint._carly_v55_model_intelligence = True
        endpoint._carly_v55_prior = prior
        route.endpoint = endpoint
        dependant.call = endpoint
        log.warning("CARLY_V55 installed model_intelligence_precedence=true")
        return
