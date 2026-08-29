"""Deterministic, verification-aware vehicle briefs for Carly.

Common vehicle enquiries should feel like advice, not FAQ copy. This module keeps
that path at zero LLM calls by combining listing facts, conservative model-family
knowledge, shortlist position and CarTrade's verification handoff.
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


# Broad ownership tendencies only. Never use these as claims about the exact
# equipment, condition or history of one listing.
_MODEL_GUIDANCE = (
    (re.compile(r"\bmirage(?: g4)?\b", re.I), {
        "pros": "su tamaño, simplicidad y enfoque de bajo consumo tienen mucho sentido en ciudad",
        "cons": "la contrapartida suele ser menos potencia, aislamiento y refinamiento que en un compacto mayor",
    }),
    (re.compile(r"\balto\b", re.I), {
        "pros": "es de los formatos más pequeños y fáciles de estacionar, con una propuesta muy orientada a costo urbano",
        "cons": "es un carro básico: confort, seguridad y equipamiento pueden variar bastante según la versión exacta",
    }),
    (re.compile(r"\bpicanto\b", re.I), {
        "pros": "combina huella urbana, maniobrabilidad y una cabina más utilizable que varios city cars muy pequeños",
        "cons": "sigue siendo un city car; espacio, desempeño en carretera y aislamiento quedan por debajo de segmentos mayores",
    }),
    (re.compile(r"\bspark\b", re.I), {
        "pros": "su huella pequeña y costo de entrada lo hacen natural para trayectos urbanos",
        "cons": "espacio, refinamiento y desempeño son modestos frente a hatchbacks de un segmento superior",
    }),
    (re.compile(r"\bswift\b", re.I), {
        "pros": "es ligero, compacto y suele sentirse muy natural para uso urbano sin ser tan espartano como un city car puro",
        "cons": "espacio trasero y aislamiento siguen siendo más limitados que en alternativas de mayor tamaño",
    }),
    (re.compile(r"\bfit\b|\bjazz\b", re.I), {
        "pros": "aprovecha excepcionalmente bien el espacio para su tamaño y conserva una huella urbana",
        "cons": "en unidades más antiguas, historial y desgaste de la unidad pesan más que la buena reputación general del modelo",
    }),
    (re.compile(r"\bfabia\b", re.I), {
        "pros": "ofrece un buen punto medio entre tamaño urbano, practicidad y sensación de carro más completo",
        "cons": "conviene confirmar soporte local, repuestos y mantenimiento de la versión exacta antes de preferirlo a marcas más comunes",
    }),
    (re.compile(r"\brio\b", re.I), {
        "pros": "es un hatch/sedán pequeño pero más versátil que un city car puro para uso mixto",
        "cons": "esa versatilidad también significa más tamaño y normalmente más costo que Alto, Picanto o Mirage",
    }),
    (re.compile(r"\bforte\b|\bcerato\b", re.I), {
        "pros": "aporta más espacio y comodidad si el uso se extiende más allá de trayectos urbanos cortos",
        "cons": "para una misión centrada en economía y estacionamiento fácil, es más carro del que realmente necesitas",
    }),
    (re.compile(r"\bcivic\b", re.I), {
        "pros": "es una plataforma compacta más completa para uso mixto, carretera y ciudad",
        "cons": "en usados la unidad manda: kilometraje, reparaciones, historial y precio pueden convertir un buen modelo en una mala compra",
    }),
    (re.compile(r"\bjett?a\b", re.I), {
        "pros": "es cómodo y más apto para carretera o uso mixto que un city car",
        "cons": "es sensiblemente más grande y menos alineado con una búsqueda cuyo norte es estacionar fácil y gastar poco",
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
            "pros": "el formato hatchback encaja bien con una misión urbana y aprovecha bien el espacio exterior",
            "cons": "sin datos más específicos de la versión, la unidad debe ganar por precio, kilometraje y condición",
        }
    if body == "sedan":
        return {
            "pros": "puede aportar más comodidad y versatilidad para trayectos mixtos",
            "cons": "cede frente a un hatchback pequeño cuando la prioridad es maniobrabilidad y estacionamiento",
        }
    return {
        "pros": "puede encajar por precio y disponibilidad",
        "cons": "necesita más evidencia antes de saber si realmente supera a los finalistas",
    }


def verification_plan(country: str | None = None) -> list[str]:
    """Checks Carly can promise as a process, never as already-completed facts."""
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
            facts.append(f"~${monthly:,.0f}/mes y ~${max(0.0, ceiling-monthly):,.0f}/mes de margen")
        else:
            facts.append(f"~${monthly:,.0f}/mes")
    elif price is not None:
        facts.append(f"${price:,.0f} publicados")
    return facts[:3]


def build_vehicle_brief(latest: str, visible: list[dict], profile: Any, country: str | None = None) -> dict | None:
    """Return a compact structured brief for normal advisor enquiries."""
    n = _norm(latest)
    triggers = (
        "cuentame", "hablame", "dime mas", "mas info", "informacion", "pros", "contras",
        "que tal", "como lo ves", "que piensas", "que opinas", "por que", "preocupa",
        "preocupar", "deberia saber", "vale la pena", "comprarias", "elegirias", "revisar",
        "validar", "ventajas", "desventajas",
    )
    focus = _find_focus(latest, visible)
    wants_choice = any(t in n for t in ("cual comprarias", "cual elegirias", "por cual"))
    if not any(t in n for t in triggers) and not wants_choice:
        return None

    ranked = sorted(list(visible or []), key=lambda c: advisor_score(c, profile), reverse=True)
    if focus is None:
        if wants_choice and ranked:
            focus = ranked[0]
        else:
            return None

    name = _name(focus)
    snap = advisor_snapshot(focus, profile)
    guidance = model_guidance(focus)
    pos = next((i + 1 for i, car in enumerate(ranked) if car is focus or (car.get("url") and car.get("url") == focus.get("url"))), None)

    if pos == 1:
        reading = f"El {name} es el que investigaría primero entre los que tienes visibles."
    elif pos and pos <= 3:
        reading = f"Mantendría el {name} como finalista, aunque no es mi #1 en esta ronda."
    else:
        reading = f"Mantendría el {name} como alternativa, no por delante de los mejores finalistas actuales."

    unit_facts = _unit_facts(focus, profile)
    reasons = list(snap.get("reasons") or [])
    why_bits = unit_facts[:2] + [r for r in reasons if r not in unit_facts][:1]
    why = "; ".join(why_bits) or "sus números actuales encajan razonablemente con tu búsqueda"

    unit_tradeoffs = list(snap.get("tradeoffs") or [])
    trade_parts = [guidance["cons"]]
    if unit_tradeoffs and "estado real" not in _norm(unit_tradeoffs[0]):
        trade_parts.append(f"En esta unidad, {unit_tradeoffs[0]}")

    compare = ""
    if ranked:
        leader = ranked[0]
        same = leader is focus or (leader.get("url") and leader.get("url") == focus.get("url"))
        if not same:
            compare = f"Pondría antes al {_name(leader)} por su mejor ajuste global a esta búsqueda."
        elif len(ranked) > 1:
            compare = f"Su rival más cercano aquí es el {_name(ranked[1])}."
    if compare:
        trade_parts.append(compare)
    trade = ". ".join(part.rstrip(". ") for part in trade_parts if part) + "."

    verify = verification_plan(country)
    cartrade = (
        "Antes de avanzar, CarTrade valida identidad del vendedor, documentación de propiedad/registro, "
        "consistencia de placa/VIN/chasis y restricciones relevantes de transferencia; después aplica la "
        "verificación física/mecánica correspondiente. Hasta completar esos checks, Carly lo trata como pendiente, no como confirmado."
    )

    sections = [
        {"title": "Mi lectura", "text": reading},
        {"title": "Por qué me gusta", "text": f"{why}. {guidance['pros'].capitalize()}."},
        {"title": "Ojo con", "text": trade},
        {"title": "CarTrade lo verifica", "text": cartrade},
    ]
    # The current frontend may collapse whitespace. The centered dot keeps the
    # hierarchy scannable even before it starts rendering response_sections natively.
    reply = "\n\n".join(f"{section['title'].upper()} · {section['text']}" for section in sections)
    return {
        "reply": reply,
        "sections": sections,
        "focus": name,
        "verification_plan": verify,
        "llm_calls": 0,
        "token_path": "deterministic_vehicle_brief",
    }
