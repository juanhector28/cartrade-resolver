"""Pure commercial-advisory primitives for Carly.

Keeps Carly rigorous while making the experience sales-positive. This module is
intentionally deterministic: it adds advisor/financing UX without extra LLM calls.
"""
from __future__ import annotations

import math
import re
from typing import Any


COMMERCIAL_PROMPT = r"""

# CARLY COMO ASESORA COMERCIAL DE COMPRA
Ayuda al comprador a avanzar hacia una buena compra con criterio y claridad.
Financiamiento es una herramienta, nunca una meta. No recomiendes un peor auto
para empujar credito.

- Si falta capacidad de pago, prioriza cuota mensual comoda.
- Si ya dio una cuota mensual, NO vuelvas a preguntar si prefiere cuota o precio.
- Si tiene efectivo para prima, no asumas que debe usarlo todo. Explica el trade-off
  entre bajar cuota/interes y conservar liquidez.
- Toma posicion: cuando haya shortlist, di cual elegirias y por que.
- Nunca rellenes cupos con opciones flojas solo para llegar a un numero.
"""


_BUDGET_QUESTION_PATTERNS = (
    re.compile(r"cu[aá]nto\s+(?:puedes|podr[ií]as)\s+(?:destinar|pagar).{0,60}(?:mes|cuota|precio)", re.I | re.S),
    re.compile(r"(?:cuota|presupuesto).{0,40}(?:m[aá]xim[oa]|mensual|total)", re.I | re.S),
)
_MONTHLY_SIGNAL_RE = re.compile(
    r"(?:\$\s*)?\d[\d.,]*\s*(?:/\s*mes|al\s+mes|mensuales?|por\s+mes)|"
    r"(?:cuota|mensual).{0,30}(?:\$\s*)?\d",
    re.I,
)
_DOWN_PAYMENT_SIGNAL_RE = re.compile(
    r"(?:prima|enganche|inicial|down\s*payment).{0,30}(?:\$\s*)?(\d[\d.,]*)(?:\s*k)?|"
    r"(?:\$\s*)?(\d[\d.,]*)(?:\s*k)?\s*(?:de\s+)?(?:prima|enganche|inicial|down\s*payment)",
    re.I,
)


def combined_user_text(messages: list[Any] | None) -> str:
    out = []
    for m in messages or []:
        if isinstance(m, dict):
            role, content = m.get("role"), m.get("content")
        else:
            role, content = getattr(m, "role", None), getattr(m, "content", None)
        if str(role or "").lower() == "user":
            out.append(str(content or ""))
    return "\n".join(out)


def has_monthly_signal(messages: list[Any] | None) -> bool:
    return bool(_MONTHLY_SIGNAL_RE.search(combined_user_text(messages)))


def preferred_budget_question(reply: str) -> str:
    """Normalize the first affordability question into a low-friction choice."""
    text = (reply or "").strip()
    if not text:
        return text
    if any(p.search(text) for p in _BUDGET_QUESTION_PATTERNS) and "?" in text:
        prefix = text.split("?", 1)[0]
        if len(prefix) > 120 or "cuánto" in prefix.lower() or "cuanto" in prefix.lower():
            prefix = ""
        prefix = prefix.strip()
        if prefix and not prefix.endswith((".", "!", ":")):
            prefix += "."
        q = "¿Prefieres pensar en precio total o en una cuota mensual cómoda?"
        return (prefix + " " + q).strip()
    return text


_TONE_REWRITES = (
    (re.compile(r"qu[eé]\s+deber[ií]a\s+preocuparte", re.I), "qué validaría antes de avanzar"),
    (re.compile(r"qu[eé]\s+te\s+deber[ií]a\s+preocupar", re.I), "qué validaría antes de avanzar"),
    (re.compile(r"red\s+flags?", re.I), "señales que revisaría"),
    (re.compile(r"banderas?\s+rojas?", re.I), "señales que revisaría"),
    (re.compile(r"riesgos?\s+principales", re.I), "puntos principales por confirmar"),
)


def soften_advisory_tone(reply: str) -> str:
    text = reply or ""
    for pattern, replacement in _TONE_REWRITES:
        text = pattern.sub(replacement, text)
    return text


def financing_for_car(car: dict) -> dict:
    monthly = car.get("monthly_est")
    available = monthly is not None
    return {
        "available": available,
        "monthly_est": monthly,
        "estimate": bool(available),
        "label": f"Aprox. ${float(monthly):,.0f}/mes con CarTrade" if available else "Explorar financiamiento con CarTrade",
        "cta": "Ver financiamiento",
        "disclaimer": "Estimado sujeto a pre-calificación y condiciones finales." if available else "Sujeto a pre-calificación.",
    }


def monthly_payment(principal: float, apr: float, months: int) -> float:
    """Deterministic amortization helper. Zero token cost."""
    principal = max(0.0, float(principal or 0))
    months = max(1, int(months or 1))
    rate = max(0.0, float(apr or 0)) / 12.0
    if rate == 0:
        return principal / months
    return principal * rate / (1 - math.pow(1 + rate, -months))


def financing_scenarios(price: float, cash_available: float, apr: float = 0.12, months: int = 60) -> list[dict]:
    """Compare a few useful down-payment levels without an LLM."""
    price = max(0.0, float(price or 0))
    cash = max(0.0, min(float(cash_available or 0), price))
    candidates = sorted({0.0, min(2500.0, cash), min(5000.0, cash), cash})
    out = []
    for down in candidates:
        financed = max(0.0, price - down)
        monthly = monthly_payment(financed, apr, months)
        total_interest = max(0.0, monthly * months - financed)
        out.append({
            "down_payment": round(down, 2),
            "amount_financed": round(financed, 2),
            "monthly_payment": round(monthly, 2),
            "total_interest": round(total_interest, 2),
            "cash_retained": round(max(0.0, cash - down), 2),
        })
    return out


def _top_pick(cards: list[dict]) -> dict | None:
    if not cards:
        return None
    # Upstream ranking is authoritative. Do not spend tokens re-ranking it.
    return cards[0] if isinstance(cards[0], dict) else None


def _advisor_metadata(result: dict) -> None:
    cards = [c for c in (result.get("recommendations") or []) if isinstance(c, dict)]
    if not cards:
        return
    top = _top_pick(cards)
    if not top:
        return
    name = " ".join(str(x) for x in (top.get("make"), top.get("model"), top.get("year")) if x)
    result["advisor"] = {
        "position": "top_pick",
        "top_pick": {
            "id": top.get("id"),
            "url": top.get("url"),
            "name": name,
            "monthly_est": top.get("monthly_est"),
            "price_usd": top.get("price_usd"),
            "match_pct": top.get("match_pct"),
        },
        "actions": [
            {"id": "why_this", "label": "¿Por qué este?"},
            {"id": "why_not", "label": "¿Por qué no otro?"},
            {"id": "find_better", "label": "Encuéntrame uno mejor"},
            {"id": "optimize_financing", "label": "Optimizar financiamiento"},
        ],
        "recommendation_policy": "quality_over_quota",
    }
    # Frontend can ask once before expanding. 3 is the product-recommended default.
    result["recommendation_depth"] = {
        "default": 3,
        "choices": [3, 5, 10],
        "never_fill_below_quality_threshold": True,
    }


def decorate_financing(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    cards = result.get("recommendations") or []
    for car in cards:
        if isinstance(car, dict):
            car["financing"] = financing_for_car(car)

    decision = result.get("decision")
    if isinstance(decision, dict):
        for car in decision.get("recommendations") or []:
            if isinstance(car, dict):
                car["financing"] = financing_for_car(car)
        decision["financing"] = {
            "positioning": "cash_optimizer",
            "optional": True,
            "cta": "Optimizar financiamiento",
        }

    if result.get("phase") == "recommendation":
        result["financing"] = {
            "available": any(isinstance(c, dict) and c.get("monthly_est") is not None for c in cards),
            "positioning": "cash_optimizer",
            "optional": True,
            "cta": "Optimizar financiamiento",
        }
        _advisor_metadata(result)
    return result


def commercialize_response(result: Any, messages: list[Any] | None = None) -> Any:
    if not isinstance(result, dict):
        return result
    if isinstance(result.get("reply"), str):
        reply = result["reply"]
        # If the buyer already supplied a monthly number, never regress to the
        # generic price-vs-payment question. This is deterministic state reuse.
        if not has_monthly_signal(messages):
            reply = preferred_budget_question(reply)
        else:
            reply = re.sub(
                r"¿Prefieres pensar en precio total o en una cuota mensual cómoda\?",
                "",
                reply,
                flags=re.I,
            ).strip()
        result["reply"] = soften_advisory_tone(reply)
    return decorate_financing(result)
