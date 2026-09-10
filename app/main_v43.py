"""Carly v43: stage-level recommendation latency observability.

Preserves v42/v41 product behavior. Adds timing around focused retrieval,
ranking (including finalist safety enrichment), and the focused rebuild so P0
latency can be attributed before changing decision quality.
"""
from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Any

from . import main_v42 as v42

app = v42.app
v41 = v42.v41
v39 = v41.v39
v36 = v41.v36
v31 = v41.v31
log = logging.getLogger("carly.latency.stage")

try:
    v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v43-stage-timing"
except Exception:
    pass


def _timed(name: str, fn):
    if getattr(fn, "_carly_v43_timed", False):
        return fn

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        started = time.perf_counter()
        outcome = "ok"
        try:
            return fn(*args, **kwargs)
        except Exception:
            outcome = "error"
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            log.warning("CARLY_STAGE stage=%s elapsed_ms=%s outcome=%s", name, elapsed_ms, outcome)

    wrapper._carly_v43_timed = True
    wrapper._carly_v43_prior = fn
    return wrapper


def _install_stage_timing() -> None:
    # _rebuild resolves _query_rows from v39 and _rank_rows from v31 dynamically.
    v39._query_rows = _timed("focused_retrieval", v39._query_rows)

    # v36._rank_rows invokes _scan_uncached_finalists from its module globals.
    # Time that separately before wrapping the whole ranking stage so the two
    # measurements can be compared without changing execution order.
    v36._scan_uncached_finalists = _timed("finalist_vision", v36._scan_uncached_finalists)
    v31._rank_rows = _timed("rank_and_enrichment", v31._rank_rows)

    v39._rebuild = _timed("focused_rebuild_total", v39._rebuild)


_install_stage_timing()
