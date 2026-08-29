"""Production commercial-advisory layer for Carly.

Sits above preview-first and preserves every existing decision/state/grounding
layer while making financing discoverable. The wrapper itself makes no LLM call.
"""
from __future__ import annotations

import os
from typing import Any

from . import main_preview as preview
from .carly_commercial import COMMERCIAL_PROMPT, commercialize_response

app = preview.app
legacy = preview.legacy
guarded = preview.guarded

RUNTIME_COMPOSITION = "commercial-v3-token-fastpath"


try:
    if COMMERCIAL_PROMPT.strip() not in str(legacy.CARLY_SYSTEM_PROMPT):
        legacy.CARLY_SYSTEM_PROMPT += COMMERCIAL_PROMPT
except Exception:
    pass
try:
    if COMMERCIAL_PROMPT.strip() not in str(guarded._FOLLOWUP_SYSTEM_PROMPT):
        guarded._FOLLOWUP_SYSTEM_PROMPT += COMMERCIAL_PROMPT
except Exception:
    pass


@app.get("/carly/runtime")
def carly_runtime():
    """Cheap deploy marker used by CI before any paid LLM smoke calls."""
    return {
        "ok": True,
        "composition": RUNTIME_COMPOSITION,
        "token_strategy": "rules-first",
        "intake_fastpath": True,
        "followup_max_tokens": 320,
        "git_commit": os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or None,
    }


def _request_body(args, kwargs):
    try:
        return guarded._request_body(args, kwargs)
    except Exception:
        return None


def _patch_commercial_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue
        prior = endpoint

        def commercial_endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = _request_body(args, kwargs)
            result = __prior(*args, **kwargs)
            messages = list(getattr(body, "messages", None) or []) if body is not None else []
            return commercialize_response(result, messages=messages)

        route.endpoint = commercial_endpoint
        dependant.call = commercial_endpoint
        break


_patch_commercial_route()
