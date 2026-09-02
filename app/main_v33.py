"""Carly v33: explicit transmission + total-budget parser hardening.

v32 remains the recommendation/quality engine. v33 fixes natural-language
constraint gaps found by adversarial tests:
1) explicit transmission is hard unless the user clearly softens it;
2) explicit rejection of one transmission can resolve the other;
3) normal cash/total-budget phrasing is parsed as a purchase-price ceiling;
4) mixed total + monthly budgets do not contaminate each other.
"""
from __future__ import annotations

import re
from typing import Any

from . import main_v32 as v32

app = v32.app
v31 = v32.v31
v28 = v31.v28

# Compatibility aliases used by regression suites and debugging helpers.
_body = v32._body
_price_anomaly = v32._price_anomaly
_effective_constraints = v32._effective_constraints
_rank_rows = v32._rank_rows

_ORIG_CONSTRAINTS = v31._constraints
_ORIG_APPLY = v32._apply

try:
    v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v33-constraint-parser"
except Exception:
    pass

_SOFT_TRANSMISSION = re.compile(
    r"\b(?:prefiero|preferir[ií]a|preferiblemente|idealmente|de preferencia|si se puede|si es posible|"
    r"me gustar[ií]a que fuera)\b",
    re.I,
)
_AUTO = re.compile(r"\b(?:autom[aá]tic[oa]|transmisi[oó]n\s+autom[aá]tica)\b", re.I)
_MANUAL = re.compile(r"\b(?:manual|mec[aá]nic[oa]|transmisi[oó]n\s+manual)\b", re.I)

_TOTAL_CUE = re.compile(
    r"\b(?:de contado|al contado|precio total|presupuesto(?: total)?|tengo hasta|cuento con|"
    r"puedo gastar(?: hasta)?|quiero gastar(?: hasta)?|pagar(?: hasta)?|m[aá]ximo total|tope total|"
    r"no quiero pasar de|no pasar de|no m[aá]s de|como m[aá]ximo|hasta)\b",
    re.I,
)
_CASH_AFTER = re.compile(r"\b(?:de contado|al contado)\b", re.I)
_MONEY = re.compile(
    r"(?:(?:US\$|USD|\$)\s*)?([0-9]{1,3}(?:[.,][0-9]{3})+|[0-9]{4,6}|[0-9]+(?:[.,][0-9]+)?)\s*(k|mil)?\b",
    re.I,
)
_MONTHLY_AFTER = re.compile(r"^\s*(?:al mes|mensual(?:es)?|por mes|de cuota(?: mensual)?|cuota mensual)\b", re.I)


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
    """Extract an actual purchase-price ceiling without stealing years/monthly figures."""
    text = text or ""
    if not _TOTAL_CUE.search(text):
        return None

    candidates: list[tuple[int, float]] = []
    for match in _MONEY.finditer(text):
        value = _money_number(match.group(1), match.group(2))
        if value is None or value < 2000 or value > 500000:
            continue

        raw_match = match.group(0)
        has_currency = bool(re.search(r"US\$|USD|\$", raw_match, re.I))
        has_suffix = bool(match.group(2))
        # Bare four-digit years are not budgets.
        if 1980 <= value <= 2100 and not has_currency and not has_suffix:
            continue

        prefix = text[max(0, match.start() - 60):match.start()]
        suffix = text[match.end():match.end() + 36]
        cue_before = bool(_TOTAL_CUE.search(prefix))
        cash_after = bool(_CASH_AFTER.search(suffix))
        if not cue_before and not cash_after:
            continue
        if _MONTHLY_AFTER.search(suffix):
            continue
        candidates.append((match.start(), value))

    if not candidates:
        return None
    return float(candidates[-1][1])


def _transmission_is_soft(text: str, token_match: re.Match[str]) -> bool:
    start = max(0, token_match.start() - 52)
    end = min(len(text), token_match.end() + 42)
    return bool(_SOFT_TRANSMISSION.search(text[start:end]))


def _transmission_is_negated(text: str, token_match: re.Match[str]) -> bool:
    start = max(0, token_match.start() - 28)
    prefix = text[start:token_match.start()]
    return bool(re.search(r"\b(?:no|sin)\s+(?:(?:quiero|quisiera)\s+|(?:que\s+)?sea\s+)?$", prefix, re.I))


def _semantic_transmission(text: str) -> str | None:
    auto = _AUTO.search(text)
    manual = _MANUAL.search(text)
    auto_neg = bool(auto and _transmission_is_negated(text, auto))
    manual_neg = bool(manual and _transmission_is_negated(text, manual))

    if auto and manual:
        if auto_neg and not manual_neg:
            return "manual"
        if manual_neg and not auto_neg:
            return "automatic"
        # Both positive means the user allowed both or expressed an unresolved choice.
        return None
    if auto:
        if auto_neg or _transmission_is_soft(text, auto):
            return None
        return "automatic"
    if manual:
        if manual_neg or _transmission_is_soft(text, manual):
            return None
        return "manual"
    return None


def _constraints(body: Any) -> dict[str, Any]:
    c = dict(_ORIG_CONSTRAINTS(body))
    text = str(c.get("text") or "")

    # Recompute from semantic wording so legacy false positives (e.g. "No quiero automática")
    # cannot survive into the hard-filter layer.
    if _AUTO.search(text) or _MANUAL.search(text):
        c["require_transmission"] = _semantic_transmission(text)

    # Prefer the explicit v33 total parser over legacy extraction, which can mistake a year
    # for a budget in mixed exact-model prompts.
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
