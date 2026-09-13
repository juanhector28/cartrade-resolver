"""Carly v54: deterministic continuation for post-shortlist "more options".

The live UI can ask for more vehicles after Carly has already surfaced a shortlist.
That intent must never fall through to a generic explanatory reply. Reuse the
existing v16 deterministic continuation search before the later recommendation
stack can rebuild/overwrite it.
"""
from __future__ import annotations

import logging
import re
from functools import wraps
from typing import Any

from . import main_v16 as v16
from . import main_v50 as v50

log = logging.getLogger("carly.v54")

_MORE_RE = re.compile(
    r"(?:\b(?:mas|más|otras?|siguientes)\s+(?:opciones?|carros?|veh[ií]culos?)\b|"
    r"\b(?:ver|mostrar|muestrame|muéstrame|dame)\s+(?:mas|más)\b)",
    re.I,
)
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


def _latest_user(body: Any) -> str:
    messages = list(_get(body, "messages", []) or [])
    for message in reversed(messages):
        role = str(_get(message, "role", "") or "").lower()
        if role == "user":
            return _buyer_text(_get(message, "content", ""))
    return ""


def _is_more_options(body: Any) -> bool:
    shown = list(_get(body, "shown_cars", []) or [])
    return bool(shown and _MORE_RE.search(_latest_user(body)))


def _continuation(body: Any) -> dict | None:
    if not _is_more_options(body):
        return None
    try:
        result = v16._dynamic_search(body)
    except Exception:
        log.exception("Carly v54 deterministic continuation failed")
        return None
    if not isinstance(result, dict):
        return None

    cards = list(result.get("recommendations") or [])
    if cards:
        result["reply"] = (
            f"Encontré {len(cards)} opciones adicionales que mantienen tus criterios. "
            "Las ordené para darte trade-offs distintos sin repetir los carros que ya viste."
        )
    result["route_precedence"] = "more_options_v54"
    result["continuation"] = True
    result["append_recommendations"] = True
    result["replace_recommendations"] = False
    result["clear_recommendations"] = False
    result["llm_calls"] = 0
    return result


def install(app: Any) -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None or getattr(prior, "_carly_v54_more_options", False):
            continue

        @wraps(prior)
        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = v50.v47.commercial._request_body(args, kwargs)
            direct = _continuation(body)
            if direct is not None:
                return direct
            return __prior(*args, **kwargs)

        endpoint._carly_v54_more_options = True
        endpoint._carly_v54_prior = prior
        route.endpoint = endpoint
        dependant.call = endpoint
        log.warning("CARLY_V54 installed deterministic_more_options=true")
        return
