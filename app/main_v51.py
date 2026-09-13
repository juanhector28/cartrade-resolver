"""Carly v51: vehicle-detail precedence + buyer-truth family wording.

A specific question about a visible vehicle must never be overwritten by the
shortlist rebuild stack. Family intent also must not imply a household size that
the buyer never stated.
"""
from __future__ import annotations

import logging
from functools import wraps
from typing import Any

from . import main_v14 as v14
from . import main_v50 as v50

app = v50.app
log = logging.getLogger("carly.v51")

# Remove the old hardcoded leap from family=true to "familia de cinco".
_prior_reply = v50.v31._reply


def _truthful_reply(c: dict[str, Any], top: list[dict], exact_miss: bool = False) -> str:
    reply = _prior_reply(c, top, exact_miss=exact_miss)
    try:
        passengers = int(c.get("passengers") or 0)
    except Exception:
        passengers = 0
    if c.get("family") and passengers < 5 and reply.startswith("Para una familia de cinco"):
        return (
            "Para tu uso familiar prioricé espacio real, comodidad y margen de cuota; "
            "evité opciones demasiado pequeñas o poco prácticas para ese uso."
        )
    return reply


v50.v31._reply = _truthful_reply


def _patch_vehicle_detail_precedence() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None or getattr(prior, "_carly_v51_vehicle_detail", False):
            continue

        @wraps(prior)
        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = v50.v47.commercial._request_body(args, kwargs)
            try:
                direct = v14._advisor_brief(body)
            except Exception:
                log.exception("Carly v51 vehicle-detail fastpath failed; falling through")
                direct = None
            if direct is not None:
                direct["route_precedence"] = "vehicle_detail_v51"
                direct["llm_calls"] = 0
                return direct
            return __prior(*args, **kwargs)

        endpoint._carly_v51_vehicle_detail = True
        endpoint._carly_v51_prior = prior
        route.endpoint = endpoint
        dependant.call = endpoint
        break


_patch_vehicle_detail_precedence()

# Regression guard for the exact semantic failure: family intent without an
# explicit passenger count must never assert five people.
_probe = {
    "family": True,
    "passengers": None,
    "exact": None,
    "intent": {},
    "delivery": False,
    "require_body": None,
    "require_transmission": None,
}
_probe_text = _truthful_reply(_probe, [])
if "familia de cinco" in _probe_text.lower():
    raise RuntimeError("Carly v51 family-size truth regression")

log.warning("CARLY_V51 installed vehicle_detail_precedence=true family_size_truth=true")

# v52 keeps the stable v51 production entrypoint and installs two narrowly
# scoped behavior fixes after the full v51 route composition exists.
from . import carly_v52_hotfix as _v52_hotfix
_v52_hotfix.install(app)

# v53 keeps the same production entrypoint but puts a hard interactive budget on
# optional finalist vision so a healthy recommendation request cannot outlive
# the browser's request deadline.
from . import carly_v53_latency as _v53_latency
_v53_latency.install()

# v54 gives post-shortlist "more options" explicit outermost precedence. Without
# this, later recommendation wrappers can overwrite the deterministic continuation
# and Carly answers with a generic explanation instead of fresh unseen vehicles.
from . import carly_v54_more_options as _v54_more_options
_v54_more_options.install(app)

# v55 sits outermost so questions about the MODEL (pros/cons, reliability,
# known issues) cannot be swallowed by the listing/unit brief. It also strips
# the frontend's hidden routing context before semantic follow-up processing.
from . import carly_v55_model_intelligence as _v55_model_intelligence
_v55_model_intelligence.install(app)
