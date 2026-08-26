"""Runtime guardrails for Carly.

These rules protect explicit buyer facts from being softened by ranking or by the
LLM. They are intentionally deterministic: explicit facts such as a maximum
odometer or a stated daily commute are treated as canonical until the user
changes them.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

GUARDRAIL_PROMPT = r"""
# REGLAS DE INTEGRIDAD DEL COMPRADOR (AUTORITATIVAS)
Estas reglas prevalecen sobre cualquier instruccion anterior que sea mas laxa.

1) Los hechos explicitos del comprador son canonicos hasta que EL comprador los
   cambie. Nunca conviertas 20 km diarios en 100 km, ni confundas el radio de
   busqueda geografico con distancia de uso.
2) Una restriccion explicita es DURA. Ejemplos:
   - "abajo de 65,000 km", "menos de 65 mil km", "maximo 65k km"
     -> max_km = 65000
   - "maximo $12k" -> max_price = 12000
   Ninguna recomendacion ni opcion de exploracion puede violar un hard constraint.
   Si no hay resultados, dilo y pide permiso antes de flexibilizarlo. NUNCA lo
   flexibilices silenciosamente.
3) Agrega siempre `max_km` al bloque <PROFILE> cuando el usuario haya expresado
   un techo de kilometraje:
      "max_km": <numero o null>
4) UNA pregunta por turno significa UN solo dato a responder. No unas dos
   preguntas con "y", comas o incisos.
5) Presupuesto: si el usuario responde con una cifra tipo "12k" o "$12,000" a una
   pregunta de presupuesto maximo, y no dice "al mes", "mensual" o "cuota", una
   cantidad >= 2000 se interpreta como precio total. No preguntes si $12,000 es
   una cuota mensual.
6) Un precio SOBRE mercado solo significa que la unidad esta cara frente a
   comparables. No infieras problemas mecanicos, de documentos o condicion a
   partir de que este cara. Un precio BAJO tampoco demuestra buen estado.
7) Sobre una UNIDAD concreta, no prometas "no te dara dolores de cabeza", "esta
   limpia", "esta en buen estado" ni equivalentes antes de inspeccion. Separa
   claramente conocimiento del modelo de condicion de la unidad.
8) No inventes especificaciones, equipamiento, motor, historial o condicion que
   no aparezcan en los datos estructurados que recibiste. Si hablas de una
   tendencia general del modelo, expresala como tendencia, no como hecho de esa
   unidad.
9) No uses superlativos comparativos como "el mas nuevo", "la menor cuota" o "el
   mejor precio" salvo que el sistema te haya dado explicitamente esa señal.
"""

# Numeric tokens must end in a digit. The previous expression allowed trailing
# punctuation, so a perfectly natural phrase such as "$13,000, pero..." could
# be captured as "13,000," and fail parsing, leaving an older budget active.
_NUMBER = r"[0-9]+(?:[.,][0-9]+)*"
_MAX_KM_RE = re.compile(
    rf"\b(?:abajo\s+de|menos\s+de|max(?:imo|imum)?|máximo|hasta|no\s+mas\s+de|no\s+más\s+de)"
    rf"\s*\$?\s*({_NUMBER})\s*(k|mil)?\s*(?:km|kms|kilometros|kilómetros)\b",
    re.I,
)
_DAILY_KM_RE = re.compile(
    rf"\b({_NUMBER})\s*(?:km|kms|kilometros|kilómetros)\s*"
    rf"(?:diarios?|al\s+dia|al\s+día|por\s+dia|por\s+día)\b",
    re.I,
)
_EXPLICIT_MAX_PRICE_RE = re.compile(
    rf"\b(?:max(?:imo)?|máximo|hasta|tope|techo)\s*(?:de\s*)?\$?\s*({_NUMBER})\s*(k|mil)?\b",
    re.I,
)
_STANDALONE_MONEY_RE = re.compile(
    rf"^\s*\$?\s*({_NUMBER})\s*(k|mil)?\s*(?:usd|dolares|dólares)?\s*$",
    re.I,
)

_MONTHLY_WORDS = re.compile(r"\b(?:mes|mensual|mensuales|cuota|cuotas|\/mes)\b", re.I)
_BUDGET_CONTEXT = re.compile(r"\b(?:presupuesto|budget|maximo|máximo|tope|techo|precio|cuota)\b", re.I)
_CONTEXT_BLOCK = re.compile(r"\[CONTEXTO ACTIVO DE CARTRADE:.*$", re.I | re.S)


def _message_role(message: Any) -> str:
    if isinstance(message, Mapping):
        return str(message.get("role") or "")
    return str(getattr(message, "role", "") or "")


def _message_content(message: Any) -> str:
    if isinstance(message, Mapping):
        content = message.get("content")
    else:
        content = getattr(message, "content", "")
    return str(content or "")


def _visible_user_text(text: str) -> str:
    return _CONTEXT_BLOCK.sub("", text or "").strip()


def _parse_number(raw: str, suffix: str | None = None) -> float | None:
    s = (raw or "").strip().replace(" ", "")
    if not s:
        return None
    suffix = (suffix or "").lower()

    if suffix in {"k", "mil"}:
        if "," in s and "." not in s:
            left, right = s.rsplit(",", 1)
            if len(right) <= 2:
                s = left + "." + right
            else:
                s = left + right
        elif "." in s and "," not in s:
            left, right = s.rsplit(".", 1)
            if len(right) == 3:
                s = left + right
        else:
            s = s.replace(",", "")
        try:
            return float(s) * 1000.0
        except ValueError:
            return None

    if re.search(r"[,.]\d{3}$", s):
        s = s.replace(",", "").replace(".", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def extract_explicit_facts(messages: Iterable[Any]) -> dict[str, float]:
    """Extract only high-confidence, explicitly stated numeric buyer facts.

    Messages are processed chronologically and assignments deliberately replace
    prior values. Therefore the latest explicit buyer constraint wins.
    """
    facts: dict[str, float] = {}
    previous_role = ""
    previous_text = ""

    for message in messages or []:
        role = _message_role(message).lower()
        raw_text = _message_content(message)
        text = _visible_user_text(raw_text) if role == "user" else raw_text.strip()

        if role == "user":
            for match in _MAX_KM_RE.finditer(text):
                value = _parse_number(match.group(1), match.group(2))
                if value is not None and 1000 <= value <= 1_000_000:
                    facts["max_km"] = round(value)

            for match in _DAILY_KM_RE.finditer(text):
                value = _parse_number(match.group(1))
                if value is not None and 0 < value <= 2000:
                    facts["daily_km"] = value

            for match in _EXPLICIT_MAX_PRICE_RE.finditer(text):
                tail = text[match.end():match.end() + 15]
                if re.match(r"\s*(?:km|kms|kilometros|kilómetros)\b", tail, re.I):
                    continue
                value = _parse_number(match.group(1), match.group(2))
                if value is not None and 500 <= value <= 500_000:
                    facts["max_price"] = value

            standalone = _STANDALONE_MONEY_RE.match(text)
            if (
                standalone
                and previous_role == "assistant"
                and _BUDGET_CONTEXT.search(previous_text)
                and not _MONTHLY_WORDS.search(text)
            ):
                value = _parse_number(standalone.group(1), standalone.group(2))
                if value is not None and value >= 2000:
                    facts["max_price"] = value

        previous_role = role
        previous_text = text

    return facts


def canonical_context_line(facts: Mapping[str, Any]) -> str:
    if not facts:
        return ""
    parts = []
    for key, label in (("max_km", "max_km"), ("daily_km", "daily_km"), ("max_price", "max_price")):
        value = facts.get(key)
        if value is not None:
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            parts.append(f"{label}={value}")
    if not parts:
        return ""
    return (
        "HECHOS EXPLICITOS CANONICOS DETECTADOS DEL COMPRADOR: "
        + "; ".join(parts)
        + ". Conserva exactamente estos valores en <PROFILE> salvo que el usuario los corrija."
    )


def apply_explicit_facts(data: dict, facts: Mapping[str, Any]) -> dict:
    if not isinstance(data, dict):
        return data
    for key in ("max_km", "daily_km", "max_price"):
        if facts.get(key) is not None:
            data[key] = facts[key]
    return data


def pin_hard_constraints(profile: Any, data: Mapping[str, Any]) -> Any:
    max_km = data.get("max_km")
    try:
        max_km = float(max_km) if max_km is not None else None
    except (TypeError, ValueError):
        max_km = None
    setattr(profile, "max_km", max_km)
    setattr(profile, "_hard_max_km", max_km)

    for field in ("max_price", "max_monthly", "min_year"):
        setattr(profile, f"_hard_{field}", getattr(profile, field, None))

    for field in ("require_body", "exclude_body", "require_brands", "exclude_brands"):
        setattr(profile, f"_hard_{field}", list(getattr(profile, field, None) or []))

    setattr(profile, "_hard_exclude_transmission", getattr(profile, "exclude_transmission", None))
    return profile


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _norm(value: Any) -> str:
    s = str(value or "").strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return s


def _canon_body(value: Any) -> str:
    v = _norm(value)
    aliases = {
        "hatch": "hatchback", "hb": "hatchback", "compacto": "hatchback",
        "camioneta": "suv", "jeepeta": "suv", "yipeta": "suv", "cuv": "crossover",
        "pick-up": "pickup", "pick up": "pickup", "picap": "pickup",
        "troca": "pickup", "palangana": "pickup", "doble cabina": "pickup",
        "van": "minivan", "minibus": "minivan", "microbus": "minivan",
    }
    return aliases.get(v, v)


def _canon_transmission(value: Any) -> str:
    v = _norm(value)
    if v.startswith("auto") or "cvt" in v:
        return "automatica"
    if v.startswith("man"):
        return "manual"
    return v


def passes_pinned_constraints(car: Mapping[str, Any], profile: Any) -> bool:
    """False when a car cannot prove it satisfies an explicit hard constraint."""
    if car.get("_carly_reference_only"):
        return False

    hard_max_km = _num(getattr(profile, "_hard_max_km", None))
    if hard_max_km is not None:
        km = _num(car.get("km"))
        if km is None or km > hard_max_km:
            return False

    hard_max_price = _num(getattr(profile, "_hard_max_price", None))
    if hard_max_price is not None:
        price = _num(car.get("price_usd"))
        if price is None or price > hard_max_price:
            return False

    hard_max_monthly = _num(getattr(profile, "_hard_max_monthly", None))
    if hard_max_monthly is not None:
        monthly = _num(car.get("monthly_est"))
        if monthly is None or monthly > hard_max_monthly:
            return False

    hard_min_year = _num(getattr(profile, "_hard_min_year", None))
    if hard_min_year is not None:
        year = _num(car.get("year"))
        if year is None or year < hard_min_year:
            return False

    body = _canon_body(car.get("body_type"))
    required_bodies = {_canon_body(x) for x in getattr(profile, "_hard_require_body", []) or []}
    excluded_bodies = {_canon_body(x) for x in getattr(profile, "_hard_exclude_body", []) or []}
    if required_bodies and body not in required_bodies:
        return False
    if body in excluded_bodies:
        return False

    make = _norm(car.get("make"))
    required_brands = {_norm(x) for x in getattr(profile, "_hard_require_brands", []) or []}
    excluded_brands = {_norm(x) for x in getattr(profile, "_hard_exclude_brands", []) or []}
    if required_brands and make not in required_brands:
        return False
    if make in excluded_brands:
        return False

    excluded_transmission = getattr(profile, "_hard_exclude_transmission", None)
    if excluded_transmission and _canon_transmission(car.get("transmission")) == _canon_transmission(excluded_transmission):
        return False

    return True
