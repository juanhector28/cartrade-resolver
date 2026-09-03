"""Carly v40: tiny parser closeout on top of v39.

v39's first isolated CI caught two human-language gaps before production:
- `tampoco quiero un carro demasiado pequeño`;
- strong exact `Honda CRV` when the inherited exact helper returns no candidate.

Keep the structural v39 retrieval/ranking work unchanged and only normalize these
forms before its authoritative rebuild executes.
"""
from __future__ import annotations

import re
from typing import Any

from . import main_v39 as v39

app = v39.app
v38 = v39.v38
v37 = v39.v37
v31 = v39.v31
v28 = v39.v28

_ORIG_CONSTRAINTS = v39._constraints
_ORIG_APPLY = v39._apply

try:
    v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v40-constraint-closeout"
except Exception:
    pass

_NO_SMALL = re.compile(
    r"\b(?:(?:no|tampoco)\s+(?:quiero|quisiera)|sin)\s+(?:un\s+)?(?:carro\s+)?"
    r"(?:demasiado\s+)?peque[nñ]o\b|\b(?:no|tampoco)\s+(?:quiero|quisiera)\s+microcarros?\b",
    re.I,
)


def _candidate_exact(text: str):
    """Detect a canonical model independently of the inherited exact helper."""
    normalized = v28._norm(text or "")
    explicit_brand = None
    for alias, canonical in v31._BRAND_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            explicit_brand = canonical
            break
    for make, model, pattern, body in v39._all_model_specs():
        if pattern.search(text or "") and (explicit_brand is None or explicit_brand == make):
            return make, model, body
    return None


def _constraints(body: Any) -> dict[str, Any]:
    c = dict(_ORIG_CONSTRAINTS(body))
    text = str(c.get("text") or "")
    c["avoid_small"] = bool(c.get("avoid_small") or _NO_SMALL.search(text))

    candidate = _candidate_exact(text)
    strong = v39._strong_exact(text, candidate)
    preferred = v39._preferred_models(text)
    mentions = v39._model_mentions(text)
    if strong:
        c["exact"] = strong
    elif c.get("exact") and (preferred or len(mentions) >= 2 or v39._EQUIVALENT.search(text)):
        c["exact"] = None
    c["preferred_models"] = preferred
    return c


def _apply(body: Any, prior_result: Any) -> Any:
    # v39._apply resolves its module-level `_constraints` dynamically, so this
    # monkeypatch is authoritative without duplicating retrieval/ranking logic.
    result = _ORIG_APPLY(body, prior_result)
    if isinstance(result, dict):
        brain = dict(result.get("recommendation_brain") or {})
        if brain:
            brain["version"] = "v40"
            brain["human_parser_closeout"] = True
            result["recommendation_brain"] = brain
            result["advisor_mode"] = "recommendation_brain_v40"
    return result


# Globals dynamically resolved by v39/v31 route stack.
v39._constraints = _constraints
v31._constraints = _constraints
v37._constraints = _constraints
v31._apply = _apply
