"""Carly v41: six-seat source-truth + single-pass finalist vision.

Live v40 validation exposed two remaining production defects:
- normalized `model=Outlander` could hide source text/URL proving the unit was an
  Outlander Sport, allowing a five-seat vehicle into a 6-person shortlist;
- focused retrieval could run finalist vision once in the inherited prefilter and
  again in the authoritative v39 rebuild, creating avoidable request latency.

v41 makes source evidence authoritative for known capacity-negative variants and
skips JIT vision only during the legacy prefilter. The authoritative focused rebuild
still runs the existing cached visual safety gate, so Top recommendations keep the
same damage-screen contract without paying for duplicate scans.
"""
from __future__ import annotations

import contextvars
import re
from typing import Any

from . import main_v40 as v40

app = v40.app
v39 = v40.v39
v38 = v40.v38
v37 = v40.v37
v36 = v37.v36
v31 = v40.v31
v28 = v40.v28

_ORIG_APPLY = v40._apply
_BASE_APPLY = v39._ORIG_APPLY  # v38 apply, before v39's focused rebuild
_ORIG_MISSION_OK = v31._mission_ok
_ORIG_REPLY = v31._reply
_ORIG_SCAN_UNCACHED = v36._scan_uncached_finalists

_SKIP_PREFILTER_VISION: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "carly_v41_skip_prefilter_vision", default=False
)

try:
    v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v41-capacity-latency"
except Exception:
    pass

_OUTLANDER_SPORT = re.compile(r"\boutlander\s+sport\b", re.I)


def _source_blob(card: dict) -> str:
    """Normalize URL/title/source separators so variant evidence cannot hide."""
    blob = v28._norm(v28._card_blob(card, card))
    return re.sub(r"[-_/.]+", " ", blob)


def _mission_ok(card: dict, c: dict[str, Any]) -> bool:
    passengers = int(c.get("passengers") or 0)
    if passengers >= 6:
        # The normalized DB model can be broader than the listing itself. Source
        # evidence wins when it identifies a known five-seat derivative.
        if _OUTLANDER_SPORT.search(_source_blob(card)):
            return False
    return _ORIG_MISSION_OK(card, c)


def _reply(c: dict[str, Any], top: list[dict], exact_miss: bool = False) -> str:
    base = _ORIG_REPLY(c, top, exact_miss=exact_miss)
    passengers = int(c.get("passengers") or 0)
    if top and passengers >= 6 and not exact_miss:
        return (
            f"Para {passengers} pasajeros prioricé capacidad real de 3 filas, transmisión y presupuesto; "
            "excluí pickups y variantes que no evidencian espacio suficiente."
        )
    return base


def _scan_uncached_finalists(ranked: list[dict]) -> int:
    if _SKIP_PREFILTER_VISION.get():
        return 0
    return _ORIG_SCAN_UNCACHED(ranked)


def _focused_apply(body: Any, prior_result: Any, c: dict[str, Any]) -> dict:
    """Build legacy/profile state cheaply, then pay for vision once in final rebuild."""
    token = _SKIP_PREFILTER_VISION.set(True)
    try:
        base = _BASE_APPLY(body, prior_result)
    finally:
        _SKIP_PREFILTER_VISION.reset(token)
    if not isinstance(base, dict):
        base = {}
    return v39._rebuild(body, base, c)


def _apply(body: Any, prior_result: Any) -> Any:
    c = v40._constraints(body)
    if v39._should_retrieve(c):
        result = _focused_apply(body, prior_result, c)
    else:
        result = _ORIG_APPLY(body, prior_result)

    if not isinstance(result, dict):
        return result
    brain = dict(result.get("recommendation_brain") or {})
    if brain:
        brain["version"] = "v41"
        brain["source_truth_capacity_gate"] = True
        brain["duplicate_prefilter_vision_skipped"] = bool(v39._should_retrieve(c))
        brain["authoritative_vision_passes"] = 1 if v39._should_retrieve(c) else None
        result["recommendation_brain"] = brain
        result["advisor_mode"] = "recommendation_brain_v41"
    return result


# Dynamic globals used by the installed v31 route/ranker and v36 scanner.
v31._mission_ok = _mission_ok
v39._mission_ok = _mission_ok
v31._reply = _reply
v36._scan_uncached_finalists = _scan_uncached_finalists
v31._apply = _apply
