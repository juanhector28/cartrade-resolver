"""Production commercial-advisory layer for Carly.

Sits above preview-first and preserves every existing decision/state/grounding
layer while making financing discoverable and keeping Carly's language
sales-positive without weakening factual rigor.
"""
from __future__ import annotations

from typing import Any

from . import main_preview as preview
from .carly_commercial import COMMERCIAL_PROMPT, commercialize_response

app = preview.app
legacy = preview.legacy
guarded = preview.guarded


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
            result = __prior(*args, **kwargs)
            return commercialize_response(result)

        route.endpoint = commercial_endpoint
        dependant.call = commercial_endpoint
        break


_patch_commercial_route()
