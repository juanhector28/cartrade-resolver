"""Carly v33: explicit transmission + total-budget parser hardening.

v32 remains the recommendation/quality engine. v33 fixes two natural-language
constraint gaps found by adversarial tests:
1) an explicitly stated transmission on an exact vehicle search is hard unless
   the user clearly softens it ("preferiría", "si se puede", etc.);
2) normal cash/total-budget phrasing such as "Tengo hasta US$12,000" is parsed
   as a total purchase ceiling rather than ignored.
"""
from __future__ import annotations

import re
from typing import Any

from . import main_v32 as v32

app = v32.app
v31 = v32.v31
v28 = v31.v28

_ORIG_CONSTRAINTS = v31._constraints
_ORIG_APPLY = v32._apply

try:
    v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v33-constraint-parser"
except Exception:
    pass

_SOFT_TRANSMISSION = re.compile(
    r"\b(?:preferir[ií]a|preferiblemente|idealmente|de preferencia|si se puede|si es posible|"
    r"me gustar[ií]a que fuera)\b",
    re.I,
)
_AUTO = re.compile(r"\b(?:autom[aá]tic[oa]|transmisi[oó]n\s+autom[aá]tica)\b", re.I)
_MANUAL = re.compile(r"\b(?:manual|mec[aá]nic[oa]|transmisi[oó]n\s+manual)\b", re.I)

_TOTAL_CUE = re.compile(
    r"\b(?:de contado|al contado|precio total|presupuesto(?: total)?|tengo hasta|cuento con|"
    r"puedo gastar(?: hasta)?|quiero gastar(?: hasta)?|pagar(?: hasta)?|m[aá]ximo total|tope total)\b",
    re.I,
)
_MONEY = re.compile(
    r"(?:(?:US\$|USD|\$)\s*)?([0-9]{1,3}(?:[.,][0-9]{3})+|[0-9]{4,6}|[0-9]+(?:[.,][0-9]+)?)\s*(k|mil)?\b",
    re.I,
)
_MONTHLY_NEAR = re.compile(r"\b(?:al mes|mensual(?:es)?|por mes|cuota(?: mensual)?)\b", re.I)


def _money_number(raw: str, suffix: str | None = None) -> float | None:
    s = (raw or "").strip().replace(" ", "")
    if not s:
        return None
    try:
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s):
            value = float(re.sub(r"[.,]", "", s))
        else:
            value = float(s.replace(",", "."))
        if suffix and suffix.lower() in {"k", "mil"}:
            value *= 1000.0
        return value
    except Exception:
        return None


def _explicit_total_budget(text: str) -> float | None:
    """Extract a purchase-price ceiling only when total/cash language is present."""
    if not _TOTAL_CUE.search(text or ""):
        return None

    candidates: list[tuple[int, float]] = []
    for match in _MONEY.finditer(text or ""):
        value = _money_number(match.group(1), match.group(2))
        if value is None or value < 2000 or value > 500000:
            continue
        # Do not steal a monthly figure from a mixed sentence.
        tail = (text or "")[match.end(): match.end() + 24]
        if _MONTHLY_NEAR.search(tail):
            continue
        candidates.append((match.start(), value))

    if not candidates:
        return None
    return float(candidates[-1][1])


def _transmission_is_soft(text: str, token_match: re.Match[str]) -> bool:
    start = max(0, token_match.start() - 45)
    end = min(len(text), token_match.end() + 35)
    window = text[start:end]
    return bool(_SOFT_TRANSMISSION.search(window))


def _transmission_is_negated(text: str, token_match: re.Match[str]) -> bool:
    start = max(0, token_match.start() - 18)
    prefix = text[start:token_match.start()]
    return bool(re.search(r"\b(?:no|sin)\s+(?:quiero\s+|sea\s+|que\s+sea\s+)?$", prefix, re.I))


def _constraints(body: Any) -> dict[str, Any]:
    c = dict(_ORIG_CONSTRAINTS(body))
    text = str(c.get("text") or "")

    # Explicit transmission is a hard filter unless the wording is clearly soft.
    if not c.get("require_transmission"):
        auto = _AUTO.search(text)
        manual = _MANUAL.search(text)
        if auto and not manual and not _transmission_is_soft(text, auto) and not _transmission_is_negated(text, auto):
            c["require_transmission"] = "automatic"
        elif manual and not auto and not _transmission_is_soft(text, manual) and not _transmission_is_negated(text, manual):
            c["require_transmission"] = "manual"

    if not c.get("total_budget"):
        total = _explicit_total_budget(text)
        if total is not None:
            c["total_budget"] = total

    return c


def _apply(body: Any, prior_result: Any) -> Any:
    result = _ORIG_APPLY(body, prior_result)
    if not isinstance(result, dict):
        return result
    brain = result.get("recommendation_brain")
    if isinstance(brain, dict) and brain.get("version") == "v32":
        brain["version"] = "v33"
        brain["explicit_transmission_parser"] = True
        brain["total_budget_parser"] = True
        result["recommendation_brain"] = brain
        result["advisor_mode"] = "recommendation_brain_v33"
    return result


# The live v31-installed route resolves these globals dynamically.
v31._constraints = _constraints
v31._apply = _apply
