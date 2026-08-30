"""Carly v20: canonical buyer-state routing.

Preserves v19 ranking/paging invariants while preventing conversational regressions
from phrase-specific intake regexes. A question that received a substantive answer
is closed; semantic interpretation may remain rich/LLM-backed downstream.
"""
from __future__ import annotations

from typing import Any

from . import main_v19 as v19
from .carly_buyer_state import build_buyer_state, next_blocker

app = v19.app
commercial = v19.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v20-canonical-buyer-state"


def _patch() -> None:
    # Replace only the blocker function used by the outer commercial fastpath.
    # Recommendation/ranking/paging remains v19.
    commercial.preview.deterministic_intake_reply = next_blocker

    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None:
            continue

        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = commercial._request_body(args, kwargs)
            result = __prior(*args, **kwargs)
            if isinstance(result, dict) and body is not None:
                messages = list(getattr(body, "messages", None) or [])
                result["buyer_state"] = build_buyer_state(messages, country=getattr(body, "country", None))
                result["buyer_state_version"] = "v20"
            return result

        route.endpoint = endpoint
        dependant.call = endpoint
        break


_patch()
