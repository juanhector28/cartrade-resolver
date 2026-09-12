"""Carly v48: typed hard-constraint authority.

Production product evaluation found a semantic collision in the legacy scalar
parser: "máximo $11,000 y máximo 80,000 km" could let the later odometer value
overwrite the total budget. Carly already has a deterministic explicit-fact
extractor that understands units; v48 makes those typed facts authoritative for
recommendation constraints instead of maintaining a second numeric truth.

No LLM call is added.
"""
from __future__ import annotations

from functools import wraps
from typing import Any

from . import main_v47 as v47
from .carly_guardrails import extract_explicit_facts

app = v47.app
v40 = v47.v40
v39 = v47.v39
v31 = v39.v31
v37 = v39.v37
v28 = v39.v28

_ORIG_CONSTRAINTS = v40._constraints
_ORIG_HARD_OK = v39._hard_ok
_ORIG_REBUILD = v39._rebuild
_ORIG_MERGE_FAST = v47._merge_fast_constraints


def _messages(body: Any) -> list[Any]:
    if isinstance(body, dict):
        return list(body.get("messages") or [])
    return list(getattr(body, "messages", None) or [])


def _typed_constraints(body: Any) -> dict[str, Any]:
    c = dict(_ORIG_CONSTRAINTS(body))
    facts = extract_explicit_facts(_messages(body))

    # Typed explicit facts are authoritative. They may correct an ambiguous
    # scalar parse, but do not manufacture a value that the buyer did not state.
    if facts.get("max_price") is not None:
        c["total_budget"] = float(facts["max_price"])
    if facts.get("max_km") is not None:
        c["max_km"] = float(facts["max_km"])
    if facts.get("daily_km") is not None:
        c["daily_km"] = float(facts["daily_km"])
    c["typed_explicit_facts"] = dict(facts)
    return c


def _hard_ok(card: dict, c: dict[str, Any]) -> bool:
    if not _ORIG_HARD_OK(card, c):
        return False
    max_km = c.get("max_km")
    if max_km is not None:
        km = v28._num(card.get("km"))
        # A hard odometer ceiling is fail-closed. If mileage is missing we
        # cannot truthfully claim the unit satisfies the buyer's constraint.
        if km is None or km > float(max_km):
            return False
    return True


def _merge_fast_constraints(c: dict[str, Any], fast: dict[str, Any]) -> dict[str, Any]:
    out = _ORIG_MERGE_FAST(c, fast)
    # The typed constraint plane outranks heuristic fast-profile scalars.
    if c.get("total_budget") is not None:
        out["total_budget"] = c["total_budget"]
    if c.get("max_km") is not None:
        out["max_km"] = c["max_km"]
    if c.get("daily_km") is not None:
        out["daily_km"] = c["daily_km"]
    if c.get("typed_explicit_facts"):
        out["typed_explicit_facts"] = dict(c["typed_explicit_facts"])
    return out


@wraps(_ORIG_REBUILD)
def _rebuild(body: Any, prior_result: dict, c: dict[str, Any]) -> dict:
    result = _ORIG_REBUILD(body, prior_result, c)
    if not isinstance(result, dict):
        return result

    profile = dict(result.get("profile") or {})
    if c.get("total_budget") is not None:
        profile["max_price"] = c["total_budget"]
    if c.get("max_km") is not None:
        profile["max_km"] = c["max_km"]
    if c.get("daily_km") is not None:
        profile["daily_km"] = c["daily_km"]
    result["profile"] = profile

    brain = dict(result.get("recommendation_brain") or {})
    hard = dict(brain.get("hard_constraints") or {})
    if c.get("max_km") is not None:
        hard["max_km"] = c["max_km"]
    if c.get("total_budget") is not None:
        hard["total_budget"] = c["total_budget"]
    brain["hard_constraints"] = hard
    brain["typed_constraint_authority"] = True
    result["recommendation_brain"] = brain
    return result


# Patch every dynamic reference used by inherited routes.
v40._constraints = _typed_constraints
v39._constraints = _typed_constraints
v31._constraints = _typed_constraints
v37._constraints = _typed_constraints
v39._hard_ok = _hard_ok
v31._hard_ok = _hard_ok
v39._rebuild = _rebuild
v47._merge_fast_constraints = _merge_fast_constraints

try:
    v47.v44.v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = (
        "commercial-v48-typed-constraints"
    )
except Exception:
    pass
