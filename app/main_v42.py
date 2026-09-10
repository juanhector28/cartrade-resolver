"""Carly v42: request-stage latency observability.

This layer intentionally changes no ranking or conversational policy. It adds
server-side timing around the production /carly/chat route so a slow buyer turn
can be attributed to Carly/backend rather than inferred from client wall time.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from . import main_v41 as v41

app = v41.app
log = logging.getLogger("carly.latency")

try:
    v41.v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v42-latency-observability"
except Exception:
    pass


def _patch_chat_latency() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None or getattr(endpoint, "_carly_v42_timed", False):
            continue
        prior = endpoint

        def timed_endpoint(*args: Any, __prior=prior, **kwargs: Any):
            request_id = uuid.uuid4().hex[:12]
            started = time.perf_counter()
            outcome = "ok"
            try:
                result = __prior(*args, **kwargs)
                return result
            except Exception:
                outcome = "error"
                raise
            finally:
                total_ms = round((time.perf_counter() - started) * 1000, 1)
                log.warning(
                    "CARLY_LATENCY request_id=%s total_ms=%s outcome=%s",
                    request_id,
                    total_ms,
                    outcome,
                )

        timed_endpoint._carly_v42_timed = True
        timed_endpoint._carly_v42_prior = prior
        route.endpoint = timed_endpoint
        dependant.call = timed_endpoint
        break


_patch_chat_latency()
