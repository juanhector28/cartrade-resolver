"""Carly v49: eliminate numeric unit collisions before retrieval.

v48 made typed explicit facts authoritative when present, but the inherited
legacy parser could still manufacture a total budget from an odometer-only
phrase such as "máximo 65,000 km". v49 removes that phantom scalar before the
single-pass retrieval decision is made.

No LLM call is added.
"""
from __future__ import annotations

from typing import Any

from . import main_v48 as v48

app = v48.app
v47 = v48.v47
v40 = v48.v40
v39 = v48.v39
v31 = v48.v31
v37 = v48.v37

_ORIG_TYPED = v48._typed_constraints


def _typed_constraints(body: Any) -> dict[str, Any]:
    c = dict(_ORIG_TYPED(body))
    facts = dict(c.get("typed_explicit_facts") or {})

    # If the only typed maximum is mileage and the legacy scalar parser copied
    # that same numeric value into total_budget, delete the phantom budget.
    max_km = facts.get("max_km")
    max_price = facts.get("max_price")
    legacy_budget = c.get("total_budget")
    if max_km is not None and max_price is None and legacy_budget is not None:
        try:
            if abs(float(legacy_budget) - float(max_km)) < 0.001:
                c["total_budget"] = None
        except (TypeError, ValueError):
            pass

    return c


# Patch all dynamic constraint references used by v47/v39 inherited routes.
v48._typed_constraints = _typed_constraints
v40._constraints = _typed_constraints
v39._constraints = _typed_constraints
v31._constraints = _typed_constraints
v37._constraints = _typed_constraints

try:
    v47.v44.v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = (
        "commercial-v49-unit-safe-constraints"
    )
except Exception:
    pass
