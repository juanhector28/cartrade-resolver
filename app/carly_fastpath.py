"""Zero-token intake parser for Carly's common purchase journeys.

This module is deliberately conservative. It only claims fields that can be
extracted with high confidence from explicit buyer language. Ambiguous or nuanced
requests fall back to Carly's LLM path.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

_NUMBER = r"[0-9]+(?:[.,][0-9]+)*"


def _norm(value: Any) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s.lower()).strip()


def _role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "")
    return str(getattr(message, "role", "") or "")


def _content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def user_text(messages: list[Any] | None) -> str:
    return "\n".join(_content(m) for m in (messages or []) if _role(m).lower() == "user").strip()


def latest_user_text(messages: list[Any] | None) -> str:
    for m in reversed(list(messages or [])):
        if _role(m).lower() == "user":
            return _content(m).strip()
    return ""


def _parse_number(raw: str, suffix: str | None = None) -> float | None:
    s = str(raw or "").strip().replace(" ", "")
    if not s:
        return None
    suffix = _norm(suffix)
    if suffix in {"k", "mil"}:
        if "," in s and "." not in s:
            left, right = s.rsplit(",", 1)
            s = left + ("." + right if len(right) <= 2 else right)
        elif "." in s and "," not in s:
            left, right = s.rsplit(".", 1)
            s = left + right if len(right) == 3 else left + "." + right
        else:
            s = s.replace(",", "")
        try:
            return float(s) * 1000
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


_MONTHLY_EXPLICIT = re.compile(
    rf"(?:\$\s*)?({_NUMBER})\s*(k|mil)?\s*(?:/\s*mes|al\s+mes|por\s+mes|mensuales?|mensual)\b|"
    rf"\b(?:cuota|mensualidad)\b[^\d$]{{0,25}}\$?\s*({_NUMBER})\s*(k|mil)?",
    re.I,
)
_MONTHLY_QUESTION = re.compile(r"\b(?:cuota|mensual|al mes|por mes|/mes)\b", re.I)
_PRICE_MAX = re.compile(
    rf"\b(?:max(?:imo)?|máximo|hasta|tope|techo|no\s+mas\s+de|no\s+más\s+de)\s*(?:de\s*)?\$?\s*({_NUMBER})\s*(k|mil)?\b",
    re.I,
)
_STANDALONE_MONEY = re.compile(rf"^\s*\$?\s*({_NUMBER})\s*(k|mil)?\s*(?:usd|dolares|dólares)?\s*$", re.I)


def _monthly_from_messages(messages: list[Any] | None) -> float | None:
    value = None
    previous_role = ""
    previous_text = ""
    for m in messages or []:
        role = _role(m).lower()
        text = _content(m).strip()
        if role == "user":
            for match in _MONTHLY_EXPLICIT.finditer(text):
                raw = match.group(1) or match.group(3)
                suffix = match.group(2) or match.group(4)
                parsed = _parse_number(raw, suffix)
                if parsed is not None and 25 <= parsed <= 5000:
                    value = parsed
            standalone = _STANDALONE_MONEY.match(text)
            if standalone and previous_role == "assistant" and _MONTHLY_QUESTION.search(previous_text):
                parsed = _parse_number(standalone.group(1), standalone.group(2))
                if parsed is not None and 25 <= parsed < 2000:
                    value = parsed
        previous_role, previous_text = role, text
    return value


def _max_price_from_messages(messages: list[Any] | None) -> float | None:
    value = None
    previous_role = ""
    previous_text = ""
    for m in messages or []:
        role = _role(m).lower()
        text = _content(m).strip()
        if role == "user":
            monthly_context = bool(_MONTHLY_QUESTION.search(text))
            if not monthly_context:
                for match in _PRICE_MAX.finditer(text):
                    parsed = _parse_number(match.group(1), match.group(2))
                    if parsed is not None and 2000 <= parsed <= 500_000:
                        value = parsed
            standalone = _STANDALONE_MONEY.match(text)
            if standalone and previous_role == "assistant" and not _MONTHLY_QUESTION.search(previous_text):
                if re.search(r"\b(?:presupuesto|precio|total|tope|techo|maximo|máximo)\b", previous_text, re.I):
                    parsed = _parse_number(standalone.group(1), standalone.group(2))
                    if parsed is not None and 2000 <= parsed <= 500_000:
                        value = parsed
        previous_role, previous_text = role, text
    return value


_JOB_PATTERNS = (
    ("delivery", re.compile(r"\b(?:delivery|reparto|repartir|entregas)\b", re.I), "trabajo"),
    ("work_vehicle", re.compile(r"\b(?:negocio|herramientas|materiales|carga|trabajo pesado|vehiculo de trabajo|vehículo de trabajo)\b", re.I), "trabajo"),
    ("family_transport", re.compile(r"\b(?:familia|hijos?|bebe|bebé|niños?|ninos?)\b", re.I), "familia"),
    ("first_car", re.compile(r"\b(?:primer carro|primer auto|mi primer vehiculo|mi primer vehículo)\b", re.I), "ciudad"),
    ("long_distance", re.compile(r"\b(?:carretera|viajes largos|larga distancia|highway)\b", re.I), "carretera"),
    ("daily_commute", re.compile(r"\b(?:ir al trabajo|ir a la oficina|commute|trayecto diario)\b", re.I), "ciudad"),
    ("city_runabout", re.compile(r"\b(?:ciudad|urbano|estacionar|parquear|compacto|compacta)\b", re.I), "ciudad"),
)


def _infer_job(text: str) -> tuple[str | None, str | None]:
    for job, pattern, usage in _JOB_PATTERNS:
        if pattern.search(text):
            return job, usage
    return None, None


def _priority(text: str) -> tuple[str | None, str | None]:
    n = _norm(text)
    if any(x in n for x in ("economico", "economica", "ahorrar", "bajo consumo", "barato de mantener", "cuota baja")):
        return "economia", "high"
    if any(x in n for x in ("confiable", "confiabilidad", "durable", "no de problemas")):
        return "confiabilidad", None
    if any(x in n for x in ("espacioso", "espacio", "maletero")):
        return "espacio", None
    if "reventa" in n:
        return "reventa", None
    return None, None


_STRONG_BODY = {
    "pickup": re.compile(r"\b(?:necesito|busco|quiero|solo|tiene que ser|debe ser)\s+(?:una\s+)?(?:pickup|pick-up|pick up)\b", re.I),
    "suv": re.compile(r"\b(?:necesito|busco|quiero|solo|tiene que ser|debe ser)\s+(?:una\s+)?suv\b", re.I),
    "sedan": re.compile(r"\b(?:necesito|busco|quiero|solo|tiene que ser|debe ser)\s+(?:un\s+)?sed[aá]n\b", re.I),
    "hatchback": re.compile(r"\b(?:necesito|busco|quiero|solo|tiene que ser|debe ser)\s+(?:un\s+)?hatch(?:back)?\b", re.I),
}

_BRANDS = (
    "Toyota", "Honda", "Nissan", "Kia", "Hyundai", "Mazda", "Suzuki", "Mitsubishi",
    "Ford", "Chevrolet", "Volkswagen", "Subaru", "Jeep", "BMW", "Mercedes-Benz", "Audi",
)

_MODEL_HINTS = re.compile(
    r"\b(?:corolla|yaris|hilux|rav4|civic|fit|cr-?v|rio|picanto|swift|mirage|frontier|ranger|l200|sentra|versa|elantra|tucson|sportage|jetta|golf|mazda\s*[236]|cx-?[359]|prado|4runner)\b",
    re.I,
)


def _brand_constraints(text: str) -> tuple[list[str], list[str], bool]:
    n = _norm(text)
    required: list[str] = []
    preferred: list[str] = []
    mentioned = False
    for brand in _BRANDS:
        b = _norm(brand)
        if re.search(rf"\b{re.escape(b)}\b", n):
            mentioned = True
            if re.search(rf"\b(?:solo|solamente|tiene que ser|debe ser)\s+{re.escape(b)}\b", n):
                required.append(brand)
            elif re.search(rf"\b(?:prefiero|preferiria|me gusta|ojala)\s+{re.escape(b)}\b", n):
                preferred.append(brand)
    return required, preferred, mentioned


def extract_fast_profile(messages: list[Any] | None, country: str | None = None) -> dict | None:
    """Return a safe profile for common journeys, otherwise None.

    A fast profile requires both a usable budget signal and a clear use/job. If a
    specific model or an unclassified brand request appears, the LLM keeps the
    turn because flattening that nuance could hurt recommendation quality.
    """
    text = user_text(messages)
    if not text:
        return None
    job, usage = _infer_job(text)
    monthly = _monthly_from_messages(messages)
    max_price = _max_price_from_messages(messages)
    if not job or (monthly is None and max_price is None):
        return None

    required_brands, preferred_brands, brand_mentioned = _brand_constraints(text)
    if _MODEL_HINTS.search(text):
        return None
    if brand_mentioned and not (required_brands or preferred_brands):
        return None

    require_body: list[str] = []
    for body, pattern in _STRONG_BODY.items():
        if pattern.search(text):
            require_body.append(body)

    prefer_body: list[str] = []
    if re.search(r"\bcompact[oa]\b", text, re.I) and not require_body:
        prefer_body = ["hatchback", "sedan"]

    priority, sensitivity = _priority(text)
    n = _norm(text)
    data = {
        "country": _norm(country) or None,
        "target_monthly": None,
        "max_monthly": monthly,
        "target_price": None,
        "max_price": max_price,
        "min_year": None,
        "primary_job": job,
        "secondary_job": None,
        "usage": usage,
        "daily_km": None,
        "passengers": None,
        "small_children": True if re.search(r"\b(?:bebe|bebé|niñ[oa]s?|ninos?)\b", text, re.I) else None,
        "road_mix": "city" if job in {"city_runabout", "daily_commute", "first_car"} else ("highway" if job == "long_distance" else None),
        "cargo_level": "medium" if job in {"work_vehicle", "delivery"} else None,
        "holding_period": None,
        "cost_sensitivity": sensitivity,
        "priority": priority,
        "secondary": None,
        "avoid_body": [],
        "require_body": require_body,
        "prefer_body": prefer_body,
        "intent_segment": "electrico" if re.search(r"\b(?:electrico|eléctrico|ev)\b", text, re.I) else ("hibrido" if re.search(r"\b(?:hibrido|híbrido|hybrid)\b", text, re.I) else None),
        "avoid_transmission": "manual" if re.search(r"\b(?:no|sin)\s+manual\b|\b(?:solo|tiene que ser)\s+automatic[oa]\b", text, re.I) else None,
        "avoid_brands": [],
        "prefer_brands": preferred_brands,
        "require_brands": required_brands,
        "open_to_surprise": True,
    }

    daily = re.findall(rf"\b({_NUMBER})\s*(?:km|kms)\s*(?:diarios?|al dia|al día|por dia|por día)\b", text, re.I)
    if daily:
        parsed = _parse_number(daily[-1])
        if parsed is not None and 0 < parsed <= 2000:
            data["daily_km"] = parsed

    passengers = re.findall(r"\b(?:somos|viajamos|para)\s+(\d{1,2})\s+(?:personas|pasajeros)?\b", text, re.I)
    if passengers:
        p = int(passengers[-1])
        if 1 <= p <= 20:
            data["passengers"] = p

    if "pickup" in require_body and job == "city_runabout":
        # A body request without a clear usage deserves the richer path.
        return None
    return data


def intake_state(messages: list[Any] | None, country: str | None = None) -> dict:
    text = user_text(messages)
    job, usage = _infer_job(text)
    monthly = _monthly_from_messages(messages)
    price = _max_price_from_messages(messages)
    return {
        "intent_known": bool(job),
        "budget_known": monthly is not None or price is not None,
        "job": job,
        "usage": usage,
        "max_monthly": monthly,
        "max_price": price,
        "country": _norm(country) or None,
    }


def deterministic_intake_reply(messages: list[Any] | None, country: str | None = None) -> str | None:
    """Return one useful no-LLM blocker question, or None when nuance is needed."""
    state = intake_state(messages, country=country)
    if state["intent_known"] and not state["budget_known"]:
        return "Entendido. ¿Qué cuota mensual te queda cómoda?"
    if state["budget_known"] and not state["intent_known"]:
        return "Perfecto. ¿Para qué usarías el carro principalmente?"
    return None
