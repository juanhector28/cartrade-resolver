"""Carly v10 vehicle briefs.

A zero-token response layer for common vehicle enquiries. It combines listing
facts, small model-family guidance, relative shortlist position and CarTrade's
verification handoff into a scannable answer. Nothing here represents a completed
verification: the copy explicitly distinguishes current facts from checks CarTrade
must complete before closing.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .carly_advisor import advisor_score, advisor_snapshot


def _norm(value: Any) -> str:
    s = unicodedata.normalize("NFKD", str(value or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _name(car: dict) -> str:
    return " ".join(str(x) for x in (car.get("make"), car.get("model"), car.get("year")) if x).strip() or "esta unidad"


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# Compact, intentionally conservative model knowledge. These are broad ownership
# tendencies, never claims about the condition or exact equipment of a unit.
_MODEL_GUIDANCE = (
    (re.compile(r"\bmirage(?: g4)?\b", re.I), {
        "pros": "muy compacto, sencillo y orientado a bajo costo de uso",
        "cons": "prioriza economía sobre potencia, aislamiento y refinamiento",
    }),
    (re.compile(r"\balto\b", re.I), {
        "pros": "muy pequeño y fácil de mover/estacionar en ciudad",
        "cons": "es una propuesta básica; equipamiento y confort dependen mucho de la versión",
    }),
    (re.compile(r"\bpicanto\b", re.I), {
        "pros": "tamaño urbano, maniobrabilidad y una propuesta bastante equilibrada para ciudad",
        "cons": "sacrifica espacio y desempeño frente a carros de un segmento mayor",
    }),
    (re.compile(r"\bspark\b", re.I), {
        "pros": "huella pequeña y enfoque urbano de bajo costo",
        "cons": "es un city car; espacio, refinamiento y desempeño son más modestos que en un compacto mayor",
    }),
    (re.compile(r"\bswift\b", re.I), {
        "pros": "ligero, compacto y muy natural para uso urbano",
        "cons": "el espacio y aislamiento son más limitados que en sedanes o hatchbacks mayores",
    }),
    (re.compile(r"\bfit\b|\bjazz\b", re.I), {
        "pros": "formato compacto con muy buen aprovechamiento práctico del espacio",
        "cons": "en unidades más antiguas, año, historial y desgaste pesan más que la reputación general del modelo",
    }),
    (re.compile(r"\bfabia\b", re.I), {
        "pros": "hatchback compacto con buen balance entre tamaño urbano y practicidad",
        "cons": "en este mercado conviene confirmar soporte local, repuestos y mantenimiento de la versión exacta",
    }),
    (re.compile(r"\brio\b", re.I), {
        "pros": "equilibrio razonable entre tamaño, uso diario y practicidad",
        "cons": "es menos pequeño que un city car puro, así que no gana automáticamente en facilidad de estacionamiento",
    }),
    (re.compile(r"\bforte\b|\bcerato\b", re.I), {
        "pros": "sedán más amplio y cómodo para uso mixto",
        "cons": "para una misión puramente urbana ocupa más espacio que los hatchbacks pequeños",
    }),
    (re.compile(r"\bcivic\b", re.I), {
        "pros": "compacto versátil con buen equilibrio general como plataforma",
        "cons": "la unidad concreta importa muchísimo: precio, historial, reparaciones y condición deben pesar más que el nombre del modelo",
    }),
    (re.compile(r"\bjett?a\b", re.I), {
        "pros": "sedán cómodo y usable fuera de ciudad además del día a día",
        "cons": "es más grande y menos alineado con una búsqueda centrada en estacionamiento fácil",
    }),
)


def model_guidance(car: dict) -> dict:
    blob = _norm(" ".join(str(car.get(k) or "") for k in ("make", "model")))
    for pattern, guidance in _MODEL_GUIDANCE:
        if pattern.search(blob):
            return dict(guidance)
    body = _norm(car.get("body_type"))
    if body == "hatchback":
        return {
            "pros": "formato compacto y práctico para ciudad",
            "cons": "el valor real depende de la versión y del estado de esta unidad",
        }
    if body == "sedan":
        return {
            "pros": "formato práctico para uso diario y trayectos mixtos",
            "cons": "es menos compacto que un hatchback pequeño para estacionamiento urbano",
        }
    return {
        "pros": "puede encajar por precio y disponibilidad",
        "cons": "necesita más validación antes de saber si realmente supera a los finalistas",
    }


def verification_plan(country: str | None = None) -> list[str]:
    """Checks Carly can promise as a process, not as already-completed facts."""
    return [
        "identidad y legitimidad del vendedor",
        "documentación de propiedad/registro y consistencia con la unidad",
        "identificadores disponibles del vehículo (placa, VIN/chasis, según el mercado)",
        "transferibilidad y restricciones relevantes según las fuentes disponibles",
        "condición física/mecánica mediante la verificación o inspección aplicable",
    ]


def _find_focus(latest: str, visible: list[dict]) -> dict | None:
    text = _norm(latest)
    for car in visible or []:
        model = _norm(car.get("model"))
        make = _norm(car.get("make"))
        if model and model in text:
            return car
        if make and len(make) > 2 and make in text:
            return car
    return None


def _unit_facts(car: dict, profile: Any) -> list[str]:
    facts: list[str] = []
    year = _num(car.get("year"))
    km = _num(car.get("km"))
    monthly = _num(car.get("monthly_est"))
    ceiling = _num(getattr(profile, "max_monthly", None))
    price = _num(car.get("price_usd"))
    if year is not None:
        facts.append(str(int(year)))
    if km is not None:
        facts.append(f"{km:,.0f} km reportados")
    if monthly is not None:
        if ceiling:
            facts.append(f"~${monthly:,.0f}/mes, con ~${max(0.0, ceiling-monthly):,.0f}/mes de margen")
        else:
            facts.append(f"~${monthly:,.0f}/mes")
    elif price is not None:
        facts.append(f"${price:,.0f} publicados")
    return facts[:3]


def build_vehicle_brief(latest: str, visible: list[dict], profile: Any, country: str | None = None) -> dict | None:
    """Return a structured + plain-text brief for normal advisor enquiries."""
    n = _norm(latest)
    triggers = (
        "cuentame mas", "pros", "contras", "pros y contras", "que piensas", "que opinas",
        "por que", "preocupa", "preocupar", "deberia saber", "vale la pena", "comprarias",
        "elegirias", "revisar", "validar",
    )
    if not any(t in n for t in triggers):
        return None

    ranked = sorted(list(visible or []), key=lambda c: advisor_score(c, profile), reverse=True)
    focus = _find_focus(latest, visible)
    if focus is None:
        if any(t in n for t in ("cual comprarias", "cual elegirias", "por cual")) and ranked:
            focus = ranked[0]
        else:
            return None

    name = _name(focus)
    snap = advisor_snapshot(focus, profile)
    guidance = model_guidance(focus)
    pos = next((i + 1 for i, car in enumerate(ranked) if car is focus or (car.get("url") and car.get("url") == focus.get("url"))), None)

    if pos == 1:
        reading = f"Sí. Entre las opciones visibles, el {name} es el que yo investigaría primero."
    elif pos and pos <= 3:
        reading = f"Sí lo mantendría como finalista, aunque el {name} no es mi #1 en esta ronda."
    else:
        reading = f"Lo consideraría, pero no pondría al {name} por delante de los mejores finalistas que ya tienes."

    unit_facts = _unit_facts(focus, profile)
    reasons = list(snap.get("reasons") or [])
    why_bits = unit_facts[:2] + [r for r in reasons if r not in unit_facts][:1]
    why = "; ".join(why_bits) or "sus números actuales encajan razonablemente con tu búsqueda"

    unit_tradeoffs = list(snap.get("tradeoffs") or [])
    trade = guidance["cons"]
    if unit_tradeoffs and "estado real" not in _norm(unit_tradeoffs[0]):
        trade += f". En esta unidad además pesa que {unit_tradeoffs[0]}"

    compare = ""
    if ranked:
        leader = ranked[0]
        same = leader is focus or (leader.get("url") and leader.get("url") == focus.get("url"))
        if not same:
            compare = f"Yo pondría antes al {_name(leader)} por su mejor ajuste global a esta búsqueda."
        elif len(ranked) > 1:
            compare = f"Su rival más cercano aquí es el {_name(ranked[1])}."

    verify = verification_plan(country)
    verify_short = "; ".join(verify[:4])
    cartrade = (
        "Esto todavía no significa que la unidad esté verificada. Antes de pasar al cierre, "
        f"CarTrade se encarga de validar {verify_short}. Hasta completar ese proceso, Carly no lo trata como confirmado."
    )

    sections = [
        {"title": "Mi lectura", "text": reading},
        {"title": "Por qué me gusta", "text": f"{why}. Como modelo, {guidance['pros']}."},
        {"title": "Ojo con", "text": trade + (f" {compare}" if compare else "")},
        {"title": "CarTrade lo verifica", "text": cartrade},
    ]
    reply = "\n\n".join(f"{section['title'].upper()}\n{section['text']}" for section in sections)
    return {
        "reply": reply,
        "sections": sections,
        "focus": name,
        "verification_plan": verify,
        "llm_calls": 0,
        "token_path": "deterministic_vehicle_brief",
    }
