"""Carly v53 latency guard for inline finalist vision.

Production showed a healthy /carly/chat request returning 200 only after ~28s,
while the web client aborts the request at 12s. The expensive stage was the JIT
finalist-vision safety screen, not intake parsing or market retrieval.

Keep the visual gate, but make it opportunistic during the interactive request:
- inspect at most three likely finalists inline;
- wait only a small fixed budget for results;
- persist results that finish after the response so later requests benefit;
- cap concurrent background vision work to avoid a thundering herd;
- preserve v41's prefilter skip and v43's timing wrapper by replacing only the
  callable that v41 delegates to.
"""
from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait

from . import main_v36 as v36
from . import main_v41 as v41

log = logging.getLogger("carly.v53")


def _bounded_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _bounded_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


INLINE_BUDGET_SECONDS = _bounded_float("CARLY_VISION_INLINE_BUDGET_SECONDS", 4.5, 0.25, 8.0)
INLINE_MAX_LISTINGS = _bounded_int("CARLY_VISION_INLINE_MAX", 3, 0, 3)
GLOBAL_VISION_SLOTS = _bounded_int("CARLY_VISION_GLOBAL_SLOTS", 3, 1, 3)
_VISION_SLOTS = threading.BoundedSemaphore(GLOBAL_VISION_SLOTS)


def _run_one(row: dict):
    """Run one vision check only if a global slot is immediately available."""
    if not _VISION_SLOTS.acquire(blocking=False):
        return None
    try:
        return v36._vision_result(row)
    finally:
        _VISION_SLOTS.release()


def _persist_late(future: Future, row: dict) -> None:
    """Cache a late result without keeping the buyer's request open."""
    try:
        result = future.result()
    except Exception:
        return
    if result is None:
        return
    try:
        v36._persist(row, result)
    except Exception:
        log.exception("Carly late vision persistence failed")


def _bounded_scan_uncached_finalists(ranked: list[dict]) -> int:
    """Wait only a few seconds for JIT vision, then let the request continue."""
    if not v36.JIT_ENABLED or INLINE_MAX_LISTINGS <= 0:
        return 0

    pending = [
        row for row in ranked[:8]
        if isinstance(row, dict)
        and not row.get("vision_checked_at")
        and v36._risk(row.get("visible_damage_risk")) is None
        and v36._photo(row)
    ][:INLINE_MAX_LISTINGS]
    if not pending:
        return 0

    pool = ThreadPoolExecutor(max_workers=len(pending), thread_name_prefix="carly-vision")
    futures = {pool.submit(_run_one, row): row for row in pending}
    done, not_done = wait(set(futures), timeout=INLINE_BUDGET_SECONDS)

    completed = 0
    for future in done:
        row = futures[future]
        try:
            result = future.result()
        except Exception:
            result = None
        if result is not None:
            try:
                v36._persist(row, result)
                completed += 1
            except Exception:
                log.exception("Carly inline vision persistence failed")

    # Do not throw away paid work just because it missed the interactive budget.
    # Running calls finish in the worker and cache their result for the next turn.
    for future in not_done:
        row = futures[future]
        future.add_done_callback(lambda f, r=row: _persist_late(f, r))

    # Crucial: never wait for slow external image/model calls here. Running futures
    # may finish in the background; queued futures are cancelled.
    pool.shutdown(wait=False, cancel_futures=True)

    if not_done:
        log.warning(
            "CARLY_VISION_INLINE_DEADLINE budget_s=%.2f pending=%d completed=%d max_listings=%d",
            INLINE_BUDGET_SECONDS,
            len(not_done),
            completed,
            INLINE_MAX_LISTINGS,
        )
    return completed


def install() -> None:
    """Patch v41's delegated scanner while preserving the outer timing/skip stack."""
    if getattr(v41, "_carly_v53_bounded_vision", False):
        return
    v41._ORIG_SCAN_UNCACHED = _bounded_scan_uncached_finalists
    v41._carly_v53_bounded_vision = True
    log.warning(
        "CARLY_V53_LATENCY installed budget_s=%.2f inline_max=%d global_slots=%d",
        INLINE_BUDGET_SECONDS,
        INLINE_MAX_LISTINGS,
        GLOBAL_VISION_SLOTS,
    )
