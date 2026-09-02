"""Carly v34: demo safety hotfix for exact-model recognition, URL risk text and empty results.

This is intentionally narrow on top of v33:
- recognize Honda HR-V/HRV as an exact SUV search;
- normalize URL separators before severe-risk matching so `a-reparar`, `poco-dano`,
  etc. cannot bypass the quality gate;
- give truthful no-result language when there are zero alternatives.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

from . import main_v33 as v33

app = v33.app
v32 = v33.v32
v31 = v33.v31
v28 = v33.v28

_ORIG_CANONICAL_EXACT = v31._canonical_exact
_ORIG_HARD_RISK = v28._hard_risk
_ORIG_REPLY = v31._reply
_ORIG_APPLY = v33._apply

try:
    v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v34-demo-safety"
except Exception:
    pass

_HRV = re.compile(r"\bhr\s*[- ]?\s*v\b", re.I)
_URL_SEPARATORS = re.compile(r"[-_/%+]+")
_URL_SEVERE = re.compile(
    r"\b(?:a reparar|para reparar|poco da[nñ]o|da[nñ]o grave|da[nñ]o severo|"
    r"chocad[oa]|choque|colisi[oó]n|siniestro|salvage|rebuilt|wreck(?:ed)?|"
    r"total loss|frame damage|structural damage|no enciende|no arranca|sin pedal)\b",
    re.I,
)


def _canonical_exact(text: str):
    exact = _ORIG_CANONICAL_EXACT(text)
    if exact:
        return exact
    normalized = v28._norm(text)
    # Avoid treating a bare HR-V token as Honda if another explicit brand is present.
    if _HRV.search(text or ""):
        explicit_brand = None
        for alias, canonical in v31._BRAND_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", normalized):
                explicit_brand = canonical
                break
        if explicit_brand in {None, "Honda"}:
            return ("Honda", "HR-V", "suv")
    return None


def _url_risk_text(value: Any) -> str:
    text = unquote(str(value or ""))
    text = _URL_SEPARATORS.sub(" ", text)
    return " ".join(text.split())


def _hard_risk(card: dict, enriched: dict | None = None) -> bool:
    if _ORIG_HARD_RISK(card, enriched):
        return True
    values = []
    if isinstance(card, dict):
        values.extend([card.get("url"), card.get("title")])
    if isinstance(enriched, dict):
        values.extend([enriched.get("url"), enriched.get("title"), enriched.get("description")])
    sanitized = " ".join(_url_risk_text(v) for v in values if v)
    return bool(_URL_SEVERE.search(sanitized))


def _reply(c: dict[str, Any], top: list[dict], exact_miss: bool = False) -> str:
    if not top:
        exact = c.get("exact")
        if exact:
            label = f"{exact[0]} {exact[1]}"
            budget = f" dentro de tu máximo de ${int(c['monthly_max'])}/mes" if c.get("monthly_max") else ""
            if exact_miss and c.get("allow_alternatives") and not c.get("exact_only"):
                return f"No encontré un {label} elegible{budget}, y tampoco encontré una alternativa que pase todos tus filtros actuales."
            return f"No encontré un {label} elegible que cumpla todos tus criterios{budget}."
        return "No encontré unidades que pasen todos los filtros actuales. Puedo ampliar un criterio si quieres ver opciones cercanas."
    return _ORIG_REPLY(c, top, exact_miss=exact_miss)


def _apply(body: Any, prior_result: Any) -> Any:
    result = _ORIG_APPLY(body, prior_result)
    if not isinstance(result, dict):
        return result
    brain = result.get("recommendation_brain")
    if isinstance(brain, dict) and brain.get("version") == "v33":
        brain["version"] = "v34"
        brain["hrv_exact_model"] = True
        brain["url_risk_normalization"] = True
        brain["truthful_empty_results"] = True
        result["recommendation_brain"] = brain
        result["advisor_mode"] = "recommendation_brain_v34"
    return result


# v31's installed route resolves these module globals dynamically.
v31._canonical_exact = _canonical_exact
v28._hard_risk = _hard_risk
v31._reply = _reply
v31._apply = _apply
