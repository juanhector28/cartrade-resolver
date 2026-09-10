"""Carly v44: micro-profile the ranking hot path.

Preserves v43 product behavior and adds aggregate timings for the deterministic
ranking components. This is diagnostic only: no filters, scores, ordering, or
fallback semantics are changed.
"""
from __future__ import annotations

import contextvars
import logging
import time
from functools import wraps
from typing import Any

from . import main_v43 as v43

app = v43.app
v31 = v43.v31
v28 = v31.v28
log = logging.getLogger("carly.latency.rank")

try:
    v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v44-rank-profile"
except Exception:
    pass

_profile_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "carly_v44_rank_profile", default=None
)


def _component(name: str, fn):
    if getattr(fn, "_carly_v44_component", False):
        return fn

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        started = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            stats = _profile_ctx.get()
            if stats is not None:
                stats[name + "_ms"] = stats.get(name + "_ms", 0.0) + (
                    time.perf_counter() - started
                ) * 1000
                stats[name + "_calls"] = stats.get(name + "_calls", 0) + 1

    wrapper._carly_v44_component = True
    wrapper._carly_v44_prior = fn
    return wrapper


# Original v31 rank code resolves these names from the v31 module at runtime.
v31._hard_ok = _component("hard_ok", v31._hard_ok)
v31._quality_ok = _component("quality_ok", v31._quality_ok)
v31._mission_ok = _component("mission_ok", v31._mission_ok)
v31._score = _component("score", v31._score)
v28._dedupe = _component("dedupe", v28._dedupe)

_CURRENT_RANK = v31._rank_rows


@wraps(_CURRENT_RANK)
def _profiled_rank(rows: list[dict], c: dict[str, Any]):
    stats: dict[str, Any] = {"rows": len(rows or [])}
    token = _profile_ctx.set(stats)
    started = time.perf_counter()
    try:
        return _CURRENT_RANK(rows, c)
    finally:
        total_ms = (time.perf_counter() - started) * 1000
        _profile_ctx.reset(token)
        accounted = sum(
            float(stats.get(k, 0.0))
            for k in ("hard_ok_ms", "quality_ok_ms", "mission_ok_ms", "score_ms", "dedupe_ms")
        )
        log.warning(
            "CARLY_RANK_PROFILE rows=%s total_ms=%.1f hard_ok_ms=%.1f hard_ok_calls=%s "
            "quality_ok_ms=%.1f quality_ok_calls=%s mission_ok_ms=%.1f mission_ok_calls=%s "
            "score_ms=%.1f score_calls=%s dedupe_ms=%.1f dedupe_calls=%s other_ms=%.1f",
            stats.get("rows", 0),
            total_ms,
            stats.get("hard_ok_ms", 0.0), stats.get("hard_ok_calls", 0),
            stats.get("quality_ok_ms", 0.0), stats.get("quality_ok_calls", 0),
            stats.get("mission_ok_ms", 0.0), stats.get("mission_ok_calls", 0),
            stats.get("score_ms", 0.0), stats.get("score_calls", 0),
            stats.get("dedupe_ms", 0.0), stats.get("dedupe_calls", 0),
            max(0.0, total_ms - accounted),
        )


_profiled_rank._carly_v44_profiled = True
v31._rank_rows = _profiled_rank
