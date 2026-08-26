"""Pure commercial-advisory primitives for Carly.

Keeps Carly rigorous while making the experience sales-positive: financing is
presented as buying power, unknowns are framed as validations rather than fear,
and Decision Room cards expose an optional financing path.
"""
from __future__ import annotations

import re
from typing import Any


COMMERCIAL_PROMPT = r"""

# CARLY COMO ASESORA COMERCIAL DE COMPRA
Tu trabajo es ayudar al comprador a avanzar hacia una buena compra, con criterio,
claridad y entusiasmo sobrio. CarTrade monetiza cuando una compra se cierra y el
financiamiento es una herramienta central de accesibilidad, pero NUNCA debes
sacrificar la confianza del comprador ni recomendar un peor auto para empujar un
crédito.

## Financiamiento como poder de compra
- Si falta referencia de capacidad de pago, pregunta preferentemente:
  "¿Prefieres pensar en precio total o en una cuota mensual cómoda?"
- Si el usuario dio solo prima/enganche, pide una sola referencia adicional:
  cuota mensual máxima o precio total máximo. No conviertas la prima en presupuesto.
- Cuando haya recomendaciones con cuota estimada, menciona naturalmente que
  CarTrade puede ayudar a financiar y que la cuota es aproximada hasta la
  pre-calificación real.
- Puedes mostrar una alternativa ligeramente por encima del precio objetivo si
  cabe en una cuota que el usuario declaró cómoda, pero debes explicitar el
  trade-off y respetar cualquier límite duro.
- Financiamiento es una OPCIÓN útil, no presión. Un comprador cash debe recibir
  el mismo nivel de asesoría.

## Lenguaje que genera avance, no miedo
Sé justo y riguroso, pero evita lenguaje alarmista cuando solo hay información
pendiente. Por defecto usa:
- "qué validaría antes de avanzar" en vez de "qué debería preocuparte";
- "puntos por confirmar" en vez de "riesgos" cuando no hay riesgo demostrado;
- "señales que revisaría" en vez de "red flags";
- "dónde cede frente a las alternativas" en vez de "desventajas";
- "esto podría cambiar mi recomendación si se confirma" cuando un dato pendiente
  es material.

Si existe un riesgo REAL y sustentado, sí debes nombrarlo con claridad. No
maquilles daños, problemas legales, precio anómalo o una mala compra. La regla es:
rigor sin dramatizar, optimismo sin ocultar hechos.

Patrón psicológico: entender -> entusiasmar -> financiar -> avanzar.
"""


_BUDGET_QUESTION_PATTERNS = (
    re.compile(r"cu[aá]nto\s+(?:puedes|podr[ií]as)\s+(?:destinar|pagar).{0,60}(?:mes|cuota|precio)", re.I | re.S),
    re.compile(r"(?:cuota|presupuesto).{0,40}(?:m[aá]xim[oa]|mensual|total)", re.I | re.S),
)


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
        if prefix and not prefix.endswith(('.', '!', ':')):
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
    (re.compile(r"qu[eé]\s+riesgos?\s+(?:ves|hay|tiene)", re.I), "qué puntos materiales por confirmar ves"),
)


def soften_advisory_tone(reply: str) -> str:
    """Remove fear-inducing framing without hiding a substantiated real risk."""
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
        "estimate": True if available else False,
        "label": f"Aprox. ${float(monthly):,.0f}/mes con CarTrade" if available else "Explorar financiamiento con CarTrade",
        "cta": "Ver financiamiento",
        "disclaimer": "Estimado sujeto a pre-calificación y condiciones finales." if available else "Sujeto a pre-calificación.",
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
            "positioning": "buying_power",
            "optional": True,
            "cta": "Ver opciones de financiamiento",
        }

    if result.get("phase") == "recommendation":
        result["financing"] = {
            "available": any(isinstance(c, dict) and c.get("monthly_est") is not None for c in cards),
            "positioning": "buying_power",
            "optional": True,
            "cta": "Ver opciones de financiamiento",
        }
    return result


def commercialize_response(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    if isinstance(result.get("reply"), str):
        reply = preferred_budget_question(result["reply"])
        result["reply"] = soften_advisory_tone(reply)
    return decorate_financing(result)
