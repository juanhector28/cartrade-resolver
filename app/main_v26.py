"""Carly v26: robust zero-token intake normalization and mission-aware ranking.

Fixes concrete live regressions without adding LLM calls:
- field/construction/material-hauling language is treated as work_vehicle;
- plural/heavy cargo language is recognized;
- compact monthly ranges such as ``450-600`` are interpreted as a monthly range
  when the preceding question is about budget/payment, or when the reply says
  ``al mes`` explicitly;
- university/student commuting is recognized as a daily city mission;
- explicit total budgets are respected by the final recommendation ordering;
- the low end of a monthly range becomes the target and the high end the ceiling.

The v25 Router SHADOW pilot and all financing safety boundaries remain unchanged.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import main_v25 as v25
from . import main_preview as preview


app = v25.app
v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v26-intake-mission-quality"


def _role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "").lower()
    return str(getattr(message, "role", "") or "").lower()


def _content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _profile_value(profile: Any, key: str, default: Any = None) -> Any:
    if isinstance(profile, dict):
        return profile.get(key, default)
    return getattr(profile, key, default)


_WORK_RE = re.compile(
    r"\b(?:trabajar|trabajo|campo|finca|fincas|rural|agricultur[ao]|agricola|"
    r"ganaderia|ganadero|terraceria|ripio|escombro(?:s)?|grava|arena|cemento|"
    r"material(?:es)?|carga(?:s)?|carga(?:s)?\s+pesad(?:a|as)|trabajo\s+pesado|"
    r"obra(?:s)?|construccion|sitios?\s+de\s+construccion|herramientas|"
    r"camino(?:s)?\s+de\s+tierra|terreno(?:s)?\s+(?:rural|irregular|dificil))\b",
    re.I,
)
_STUDENT_RE = re.compile(
    r"\b(?:universidad|universitario|universitaria|uni|campus|facultad|estudiar|estudiante)\b",
    re.I,
)
_ECONOMY_RE = re.compile(
    r"\b(?:economico|economica|económico|económica|ahorrar|bajo consumo|barato de mantener|cuota baja)\b",
    re.I,
)
_KM_RE = re.compile(
    r"\b([0-9]{1,3})(?:\s*(?:-|–|—|a|hasta)\s*([0-9]{1,3}))?\s*(?:km|kms|kilometros|kilómetros)\b",
    re.I,
)
_MONTHLY_CONTEXT_RE = re.compile(
    r"\b(?:cuota|mensual|mensualidad|al mes|por mes|/mes|presupuesto|precio total)\b",
    re.I,
)
_TOTAL_BUDGET_CONTEXT_RE = re.compile(
    r"\b(?:presupuesto|precio|precio total|techo|tope|cuanto puedes gastar|cuánto puedes gastar)\b",
    re.I,
)
_APPROX_TOTAL_RE = re.compile(
    r"^\s*(?:unos?|aprox(?:imadamente)?|alrededor\s+de|como)?\s*\$?\s*([0-9]+(?:[.,][0-9]+)?)\s*(k|mil)?\s*(?:usd|dolares|dólares)?\s*$",
    re.I,
)
_RANGE_RE = re.compile(
    r"^\s*\$?\s*([0-9]{2,4})\s*(?:-|–|—|a|hasta)\s*\$?\s*([0-9]{2,4})"
    r"\s*(?:usd|dolares|dólares)?\s*(?:(al|por)\s+mes|mensual(?:es)?)?\s*$",
    re.I,
)

_CITY_ECON_MODELS = re.compile(
    r"\b(?:yaris|corolla|fit|jazz|civic|city|picanto|rio|morning|i10|grand i10|"
    r"accent|elantra|swift|celerio|alto|mirage|versa|march|micra|sentra|mazda 2|"
    r"mazda2|spark|aveo|polo|vento)\b",
    re.I,
)
_RELIABILITY_PRIOR = {
    "toyota": 13.0,
    "honda": 12.0,
    "mazda": 9.0,
    "suzuki": 8.0,
    "subaru": 8.0,
    "hyundai": 5.0,
    "kia": 5.0,
    "mitsubishi": 4.0,
    "nissan": 4.0,
    "chevrolet": 0.0,
    "ford": 0.0,
    "volkswagen": 1.0,
    "jeep": -6.0,
    "bmw": -8.0,
    "mercedes benz": -8.0,
    "audi": -8.0,
    "land rover": -12.0,
}


def _monthly_range(messages: list[Any] | None) -> tuple[float, float] | None:
    rows = list(messages or [])
    previous_role = ""
    previous_text = ""
    found = None
    for message in rows:
        role = _role(message)
        text = _content(message).strip()
        if role == "user":
            match = _RANGE_RE.match(text)
            if match:
                lo, hi = sorted((float(match.group(1)), float(match.group(2))))
                explicit_monthly = bool(match.group(3)) or "mensual" in _norm(text)
                contextual_monthly = previous_role == "assistant" and bool(_MONTHLY_CONTEXT_RE.search(previous_text))
                if 25 <= lo <= hi < 2000 and (explicit_monthly or contextual_monthly):
                    found = (lo, hi)
        previous_role, previous_text = role, text
    return found


def _approx_total_budget(text: str, previous_role: str, previous_text: str) -> float | None:
    if previous_role != "assistant" or not _TOTAL_BUDGET_CONTEXT_RE.search(previous_text):
        return None
    if re.search(r"\b(?:cuota|mensual|al mes|por mes|/mes)\b", previous_text, re.I):
        return None
    match = _APPROX_TOTAL_RE.match(text)
    if not match:
        return None
    raw = match.group(1).replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    if _norm(match.group(2)) in {"k", "mil"}:
        value *= 1000
    return value if 2000 <= value <= 500000 else None


def _student_commute_present(messages: list[Any] | None) -> bool:
    return any(_role(m) == "user" and _STUDENT_RE.search(_content(m)) for m in (messages or []))


def _daily_km(messages: list[Any] | None) -> float | None:
    value = None
    for message in messages or []:
        if _role(message) != "user":
            continue
        match = _KM_RE.search(_content(message))
        if not match:
            continue
        lo = float(match.group(1))
        hi = float(match.group(2) or match.group(1))
        if 0 < lo <= hi <= 500:
            value = (lo + hi) / 2.0
    return value


def _augment_intake(messages: list[Any] | None) -> list[dict[str, str]]:
    rows = [{"role": _role(m), "content": _content(m)} for m in (messages or [])]
    monthly_range = _monthly_range(rows)

    previous_role = ""
    previous_text = ""
    for idx, row in enumerate(rows):
        if row["role"] != "user":
            previous_role, previous_text = row["role"], row["content"]
            continue

        hints: list[str] = []
        if _WORK_RE.search(row["content"]):
            hints.append("vehiculo de trabajo materiales carga trabajo pesado")
        if _STUDENT_RE.search(row["content"]):
            hints.append("ir al trabajo trayecto diario ciudad")
            if _ECONOMY_RE.search(row["content"]):
                hints.append("economico bajo consumo ahorrar")

        match = _RANGE_RE.match(row["content"].strip())
        if match and monthly_range is not None:
            _lo, hi = monthly_range
            hints.append(f"cuota maxima {int(hi)} al mes")

        total_budget = _approx_total_budget(row["content"], previous_role, previous_text)
        if total_budget is not None:
            hints.append(f"maximo {int(total_budget)}")

        if hints:
            row["content"] = row["content"] + "\n[parser hint: " + "; ".join(hints) + "]"
        previous_role, previous_text = row["role"], row["content"]
    return rows


_prior_extract_fast_profile = preview.extract_fast_profile
_prior_deterministic_reply = preview.deterministic_intake_reply


def _v26_extract_fast_profile(messages: list[Any] | None, country: str | None = None):
    rng = _monthly_range(messages)
    student = _student_commute_present(messages)
    profile = _prior_extract_fast_profile(_augment_intake(messages), country=country)
    if profile:
        profile = dict(profile)
        if rng is not None:
            profile["target_monthly"] = rng[0]
            profile["max_monthly"] = rng[1]
        if student:
            profile["primary_job"] = "daily_commute"
            profile["usage"] = "ciudad"
            profile["road_mix"] = "city"
            km = _daily_km(messages)
            if km is not None:
                profile["daily_km"] = km
            user_blob = " ".join(_content(m) for m in (messages or []) if _role(m) == "user")
            if _ECONOMY_RE.search(user_blob):
                profile["priority"] = "economia"
                profile["cost_sensitivity"] = "high"
    return profile


def _v26_deterministic_reply(messages: list[Any] | None, country: str | None = None):
    return _prior_deterministic_reply(_augment_intake(messages), country=country)


preview.extract_fast_profile = _v26_extract_fast_profile
preview.deterministic_intake_reply = _v26_deterministic_reply


def _mission_score(car: dict, profile: Any) -> float:
    score = 50.0
    job = str(_profile_value(profile, "primary_job", "") or "")
    priority = _norm(_profile_value(profile, "priority", ""))
    body = _norm(car.get("body_type"))
    make = _norm(car.get("make"))
    model = _norm(car.get("model"))
    price = _num(car.get("price_usd"))
    max_price = _num(_profile_value(profile, "max_price"))
    year = _num(car.get("year"))
    km = _num(car.get("km"))
    monthly = _num(car.get("monthly_est"))
    max_monthly = _num(_profile_value(profile, "max_monthly"))
    delta = _num(car.get("value_delta_pct"))

    if max_price and price is not None:
        ratio = price / max_price
        if ratio > 1.05:
            score -= 100.0
        elif ratio > 1.0:
            score -= 35.0
        elif ratio >= 0.65:
            score += 6.0
        else:
            score += 1.0

    city_mission = job in {"daily_commute", "first_car", "city_runabout"}
    if city_mission:
        if body in {"hatchback", "sedan"}:
            score += 12.0
        elif body in {"crossover"}:
            score += 4.0
        elif body in {"pickup", "commercial", "minivan"}:
            score -= 28.0
        elif body == "suv":
            score -= 5.0
        if _CITY_ECON_MODELS.search(model):
            score += 10.0

    if job == "work_vehicle":
        score += 28.0 if body == "pickup" else -18.0
    elif job == "family_transport":
        if body in {"suv", "crossover", "minivan"}:
            score += 13.0
        elif body == "sedan":
            score += 4.0

    score += _RELIABILITY_PRIOR.get(make, -1.0)

    if priority == "economia":
        if _CITY_ECON_MODELS.search(model):
            score += 7.0
        if body in {"hatchback", "sedan"}:
            score += 4.0
        elif body in {"pickup", "commercial", "suv"}:
            score -= 6.0

    if year is not None:
        if year >= 2022:
            score += 10.0
        elif year >= 2019:
            score += 7.0
        elif year >= 2016:
            score += 2.0
        else:
            score -= 8.0

    if km is not None:
        if km <= 40_000:
            score += 8.0
        elif km <= 80_000:
            score += 5.0
        elif km <= 120_000:
            score += 1.0
        elif km <= 160_000:
            score -= 7.0
        else:
            score -= 13.0

    if monthly is not None and max_monthly:
        ratio = monthly / max_monthly
        if ratio <= 0.75:
            score += 4.0
        elif ratio <= 1.0:
            score += 1.0
        else:
            score -= 30.0

    if delta is not None:
        if delta <= 0:
            score += 4.0
        elif delta <= 7:
            score += 1.0
        elif delta >= 12:
            score -= 4.0

    return round(score, 2)


def _rerank_recommendation_result(body: Any, result: Any) -> Any:
    if not isinstance(result, dict) or result.get("phase") != "recommendation":
        return result
    profile_data = result.get("profile")
    if not isinstance(profile_data, dict):
        return result

    commercial = v25.v20.commercial
    try:
        profile = commercial.legacy.profile_from_extraction(dict(profile_data))
    except Exception:
        profile = profile_data

    pool = list(result.get("recommendations") or []) + list(result.get("explore") or [])
    if not pool:
        return result

    unique: list[dict] = []
    seen = set()
    for card in pool:
        if not isinstance(card, dict):
            continue
        key = card.get("url") or card.get("id") or (
            _norm(card.get("make")), _norm(card.get("model")), card.get("year"), card.get("price_usd")
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(dict(card))

    ranked = sorted(unique, key=lambda c: _mission_score(c, profile), reverse=True)
    if not ranked:
        return result
    page = ranked[:6]
    for idx, card in enumerate(page, 1):
        card["advisor_score_v26"] = _mission_score(card, profile)
        if idx == 1:
            card["best_for"] = "Mi favorita para tu caso"
            card["strategy_label"] = "Mi favorita para tu caso"
        elif idx == 2:
            card["best_for"] = "Mi segunda opción"
            card["strategy_label"] = "Mi segunda opción"
        elif idx == 3:
            card["best_for"] = "La alternativa que mantendría"
            card["strategy_label"] = "La alternativa que mantendría"

    result["recommendations"] = page[:3]
    result["explore"] = page[3:]
    result["favorite"] = page[0]
    result["recommendation_count"] = len(result["recommendations"])
    result["explore_count"] = len(result["explore"])
    result["loaded_options"] = page
    result["loaded_option_count"] = len(page)
    result["advisor_mode"] = "mission_quality_v26"

    decision = result.get("decision")
    if isinstance(decision, dict):
        decision["recommendations"] = list(result["recommendations"])
        decision["explore"] = list(result["explore"])
        decision["favorite"] = result["favorite"]
    return result


def _patch_v26_quality_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None or getattr(prior, "_carly_v26_quality", False):
            continue

        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            commercial = v25.v20.commercial
            try:
                body = commercial._request_body(args, kwargs)
            except Exception:
                body = None
            result = __prior(*args, **kwargs)
            return _rerank_recommendation_result(body, result)

        endpoint._carly_v26_quality = True
        route.endpoint = endpoint
        dependant.call = endpoint
        break


_patch_v26_quality_route()
