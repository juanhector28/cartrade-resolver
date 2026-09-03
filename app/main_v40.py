"""Carly v40: tiny parser closeout on top of v39.

v39's first isolated CI caught two human-language gaps before production:
- `tampoco quiero un carro demasiado pequeño`;
- strong exact `Honda CRV` when fallback brands later in the same prompt polluted
  the inherited global brand detector.

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
_SEARCH_ACTION = re.compile(r"\b(?:estoy\s+buscando|ando\s+buscando|busco|quiero|necesito)\b", re.I)


def _nearby_brand(text: str, start: int, end: int) -> str | None:
    """Resolve only a brand adjacent to this model mention, not a later fallback brand."""
    window = v28._norm((text or "")[max(0, start - 30):min(len(text or ""), end + 18)])
    for alias, canonical in v31._BRAND_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", window):
            return canonical
    return None


def _candidate_exact(text: str):
    """Detect model and associate brand locally around that exact mention."""
    for make, model, pattern, body in v39._all_model_specs():
        for match in pattern.finditer(text or ""):
            local_brand = _nearby_brand(text, match.start(), match.end())
            if local_brand is None or local_brand == make:
                return make, model, body
    return None


def _primary_search_exact(text: str, candidate):
    """Primary search clause wins over later `si no hay X` fallback mentions."""
    if not candidate:
        return None
    pattern = v39._pattern_for(candidate)
    if pattern is None:
        return None
    for action in _SEARCH_ACTION.finditer(text or ""):
        clause = (text or "")[action.end():action.end() + 70]
        if pattern.search(clause) and not re.search(r"\bprefier[oa]|preferir[ií]a\b", clause, re.I):
            return candidate
    return None


def _constraints(body: Any) -> dict[str, Any]:
    c = dict(_ORIG_CONSTRAINTS(body))
    text = str(c.get("text") or "")
    c["avoid_small"] = bool(c.get("avoid_small") or _NO_SMALL.search(text))

    candidate = _candidate_exact(text)
    strong = _primary_search_exact(text, candidate) or v39._strong_exact(text, candidate)
    preferred = v39._preferred_models(text)
    mentions = v39._model_mentions(text)
    if strong:
        c["exact"] = strong
    elif c.get("exact") and (preferred or len(mentions) >= 2 or v39._EQUIVALENT.search(text)):
        c["exact"] = None
    c["preferred_models"] = preferred
    return c


def _apply(body: Any, prior_result: Any) -> Any:
    result = _ORIG_APPLY(body, prior_result)
    if isinstance(result, dict):
        brain = dict(result.get("recommendation_brain") or {})
        if brain:
            brain["version"] = "v40"
            brain["human_parser_closeout"] = True
            brain["primary_exact_precedence"] = True
            brain["local_brand_model_binding"] = True
            result["recommendation_brain"] = brain
            result["advisor_mode"] = "recommendation_brain_v40"
    return result


v39._constraints = _constraints
v31._constraints = _constraints
v37._constraints = _constraints
v31._apply = _apply
