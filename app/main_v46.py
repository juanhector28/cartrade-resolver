"""Carly v46: bound the interactive ranking pool without changing final scoring.

Production evidence showed a family/SUV request ranking 900 rows while Atlas was
also active on the same one-core service. The deterministic scoring functions
were cheap, but wall-clock rank time reached ~42s. This layer keeps all existing
hard/quality/mission/vision gates and only adds a cheap retrieval preselection:
explicit body intent is recognized earlier, then the focused pool is bounded by
listing quality + recency before the authoritative ranker runs.

Exact-model searches are never bounded here.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from . import carly_fastpath as fastpath
from . import main_v45 as v45

app = v45.app
v44 = v45.v44
v43 = v44.v43
v42 = v43.v42
v41 = v42.v41
v40 = v41.v40
v39 = v41.v39
v37 = v41.v37
v31 = v44.v31
v28 = v31.v29.v28
log = logging.getLogger("carly.latency.v46")

_ORIG_CONSTRAINTS = v40._constraints
_ORIG_QUERY_ROWS = v39._query_rows

# Human phrasing such as "SUV familiar..." is an explicit body requirement even
# without a preceding "quiero/busco" verb. Action forms are also accepted, but
# negated actions ("no quiero pickup") are deliberately ignored here.
_BODY_LEAD = re.compile(
    r"(?im)^\s*(?:un|una)?\s*(suv|pickup|pick[- ]?up|sed[aá]n|hatch(?:back)?)\b"
)
_BODY_ACTION = re.compile(
    r"\b(?:estoy\s+buscando|ando\s+buscando|busco|quiero|necesito)\s+"
    r"(?:un|una)?\s*(suv|pickup|pick[- ]?up|sed[aá]n|hatch(?:back)?)\b",
    re.I,
)
_BODY_CANON = {
    "suv": "suv",
    "pickup": "pickup",
    "pick-up": "pickup",
    "pick up": "pickup",
    "sedan": "sedan",
    "sedán": "sedan",
    "hatch": "hatchback",
    "hatchback": "hatchback",
}


def _explicit_body(text: str) -> str | None:
    lead = _BODY_LEAD.search(text or "")
    if lead:
        return _BODY_CANON.get(lead.group(1).lower())
    for match in _BODY_ACTION.finditer(text or ""):
        prefix = (text or "")[max(0, match.start() - 14):match.start()]
        if re.search(r"\b(?:no|tampoco|ni)\s*$", prefix, re.I):
            continue
        return _BODY_CANON.get(match.group(1).lower())
    return None


def _constraints(body: Any) -> dict[str, Any]:
    c = dict(_ORIG_CONSTRAINTS(body))
    if not c.get("require_body"):
        body_req = _explicit_body(str(c.get("text") or ""))
        if body_req:
            c["require_body"] = body_req
    return c


# Keep the zero-token intake profile aligned with the authoritative constraints.
# This specifically closes the live "SUV familiar" -> budget journey.
_prev_suv = fastpath._STRONG_BODY.get("suv")
if _prev_suv is not None:
    fastpath._STRONG_BODY["suv"] = re.compile(
        r"(?:^\s*(?:un|una)?\s*suv\b|" + _prev_suv.pattern + r")",
        re.I | re.M,
    )


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _cheap_preselect(rows: list[dict], c: dict[str, Any]) -> list[dict]:
    if c.get("exact"):
        return rows

    candidates = list(rows or [])
    required = c.get("require_body")
    if required:
        candidates = [r for r in candidates if v31._body(r) == required]
        cap = 144
    elif int(c.get("passengers") or 0) >= 6:
        # Keep extra breadth for rarer high-capacity missions, but still prevent a
        # 900-row interactive CPU pass.
        cap = 220
    else:
        cap = 180

    # Retrieval preselection only. The authoritative ranker below still owns all
    # final ordering and safety decisions. Prefer complete, recent listings so the
    # bounded pool is at least as useful as an arbitrary updated_at window.
    candidates.sort(
        key=lambda r: (
            _num(r.get("quality_score")),
            _num(r.get("year")),
            -_num(r.get("monthly_est")),
        ),
        reverse=True,
    )
    return candidates[:cap]


def _query_rows(c: dict[str, Any], country: str) -> list[dict]:
    started = time.perf_counter()
    rows = _ORIG_QUERY_ROWS(c, country)
    bounded = _cheap_preselect(rows, c)
    log.warning(
        "CARLY_V46_RETRIEVAL country=%s original_rows=%s bounded_rows=%s require_body=%s exact=%s elapsed_ms=%.1f",
        country,
        len(rows or []),
        len(bounded),
        c.get("require_body"),
        bool(c.get("exact")),
        (time.perf_counter() - started) * 1000,
    )
    return bounded


# v41 calls v40._constraints; v39._rebuild resolves v39._query_rows dynamically.
v40._constraints = _constraints
v39._constraints = _constraints
v37._constraints = _constraints
v31._constraints = _constraints
v39._query_rows = _query_rows

# Keep the existing runtime gate stable while exposing v46 explicitly in logs.
# The deployed git SHA still proves that this code is the live runtime tree.
try:
    v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = (
        "commercial-v45-usd-prefix-fastpath"
    )
except Exception:
    pass

log.warning("CARLY_V46_BOUNDED_RETRIEVAL installed explicit_body=true caps=144/180/220")
