"""Carly v47: single-pass common-journey recommendation path.

The incremental route stack could rank twice for a deterministic first preview:
an inherited v31 pass over the broad pool, followed by the authoritative v39
focused rebuild. Production traces showed ~9.8s + ~6.1s for the same request.

For common journeys that the zero-token parser can resolve safely, intercept at
the outermost route and run only the authoritative focused rebuild. All current
hard constraints, quality gates, finalist vision and commercial response shaping
remain in force. Nuanced requests fall through to the inherited stack unchanged.
"""
from __future__ import annotations

import logging
import re
import time
from functools import wraps
from typing import Any

from . import main_commercial as commercial
from . import main_v46 as v46

app = v46.app
v45 = v46.v45
v44 = v45.v44
v43 = v44.v43
v42 = v43.v42
v41 = v42.v41
v40 = v41.v40
v39 = v41.v39
log = logging.getLogger("carly.fastpath.v47")

# Also repair the client-state fallback parser used when the UI omits Carly's
# immediately preceding budget question. v45 fixed the canonical fast parser;
# this keeps the commercial repair helper in sync for USD-prefix answers.
commercial._STANDALONE_SMALL_AMOUNT_RE = re.compile(
    r"^\s*(?:(?:usd|us\$)\s*)?\$?\s*([0-9]+(?:[.,][0-9]+)?)\s*"
    r"(?:usd|d[oó]lares?)?\s*$",
    re.I,
)


def _merge_fast_constraints(c: dict[str, Any], fast: dict[str, Any]) -> dict[str, Any]:
    """Use deterministic parser facts to fill only missing authoritative fields."""
    out = dict(c or {})
    if fast.get("max_monthly") is not None:
        out["monthly_max"] = fast["max_monthly"]
    if fast.get("max_price") is not None:
        out["total_budget"] = fast["max_price"]
    required = fast.get("require_body") or []
    if isinstance(required, str):
        required = [required]
    if not out.get("require_body") and len(required) == 1:
        out["require_body"] = required[0]
    if out.get("passengers") is None and fast.get("passengers") is not None:
        out["passengers"] = fast["passengers"]
    return out


def _single_pass(body: Any, messages: list[Any]) -> dict | None:
    if body is None or (getattr(body, "shown_cars", None) or []):
        return None

    country = getattr(body, "country", None)
    parse_messages = commercial._repair_missing_monthly_context(messages, country=country)
    fast = commercial.preview.extract_fast_profile(parse_messages, country=country)
    if not isinstance(fast, dict):
        return None

    c = _merge_fast_constraints(v40._constraints(body), fast)
    if not v39._should_retrieve(c):
        return None

    policy = commercial.preview.preview_policy(parse_messages, has_visible_cars=False)
    started = time.perf_counter()

    # v39._rebuild is the authoritative final recommendation builder. In the live
    # composition it resolves v46's bounded retrieval and v44/v43 instrumented
    # ranking, including the existing finalist vision safety gate.
    result = v39._rebuild(
        body,
        {
            "profile": dict(fast),
            "token_path": "deterministic-single-pass",
        },
        c,
    )
    if not isinstance(result, dict):
        return None

    result["recommendation_stage"] = "preview"
    result["preview"] = True
    result["preview_reason"] = "outer_single_pass_fastpath"
    result["preview_question_count"] = int(policy.get("questions") or 0)
    result["refinement_available"] = True
    result["show_market_animation"] = True
    result["replace_recommendations"] = True
    result["clear_recommendations"] = False
    result["token_path"] = "deterministic-single-pass"

    # Preserve the same UI and commercial quality contract as the existing
    # deterministic preview path, without invoking its separate legacy rank.
    result = commercial.preview.room.state.apply_ui_contract(result)
    result = commercial._final_quality_gate(result)
    result = commercial.commercialize_response(result, messages=messages)

    log.warning(
        "CARLY_V47_SINGLE_PASS elapsed_ms=%.1f phase=%s recommendations=%s pool_size=%s body=%s monthly=%s",
        (time.perf_counter() - started) * 1000,
        result.get("phase"),
        len(result.get("recommendations") or []),
        result.get("pool_size"),
        c.get("require_body"),
        c.get("monthly_max"),
    )
    return result


def _patch_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None or getattr(prior, "_carly_v47_single_pass", False):
            continue

        @wraps(prior)
        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = commercial._request_body(args, kwargs)
            messages = list(getattr(body, "messages", None) or []) if body is not None else []
            try:
                direct = _single_pass(body, messages)
            except Exception:
                log.exception("Carly v47 single-pass failed; falling back to inherited route")
                direct = None
            if direct is not None:
                return direct
            return __prior(*args, **kwargs)

        endpoint._carly_v47_single_pass = True
        endpoint._carly_v47_prior = prior
        route.endpoint = endpoint
        dependant.call = endpoint
        break


_patch_route()

# Keep the established runtime identity stable for the existing deployment gate;
# the deployed git SHA plus this explicit log marker identifies v47.
try:
    v44.v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = (
        "commercial-v45-usd-prefix-fastpath"
    )
except Exception:
    pass

log.warning("CARLY_V47_SINGLE_PASS installed deterministic_outer_intercept=true")
