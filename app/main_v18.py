"""Carly v18 recurring-failure guardrails. Deterministic and zero-token."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import main_v17 as v17
from .carly_advisor import advisor_score
from .carly_vehicle_brief import model_guidance

app = v17.app
commercial = v17.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v18-recurring-invariant-guard"
_MAX_PAGE = 6


def _norm(value: Any) -> str:
    s = unicodedata.normalize("NFKD", str(value or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _latest(body) -> str:
    try:
        return v17.v16.v15._latest(body)
    except Exception:
        return ""


def _key(car: dict):
    return v17.v16.v15._key(car)


def _unique(rows: list[dict]) -> list[dict]:
    out, seen = [], set()
    for car in rows or []:
        if not isinstance(car, dict):
            continue
        key = _key(car)
        if key in seen:
            continue
        seen.add(key); out.append(car)
    return out


def _name(car: dict) -> str:
    return " ".join(str(x) for x in (car.get("make"), car.get("model"), car.get("year")) if x).strip() or "esta unidad"


def _profile(body, shown: list[dict]):
    try:
        profile, _ = v17.v16._mutated_profile(body, shown)
        if profile is not None:
            return profile
    except Exception:
        pass
    try:
        return v17.v16.v15._profile(body, shown)
    except Exception:
        return None


def _focus(latest: str, shown: list[dict]) -> dict | None:
    text = _norm(latest)
    for car in shown:
        model = _norm(car.get("model"))
        if model and model in text:
            year = str(car.get("year") or "")
            if not year or year in text or sum(_norm(x.get("model")) == model for x in shown) == 1:
                return car
    for car in shown:
        make = _norm(car.get("make"))
        if make and make in text and sum(_norm(x.get("make")) == make for x in shown) == 1:
            return car
    return None


def _is_vehicle_brief(latest: str) -> bool:
    n = _norm(latest)
    return any(x in n for x in ("cuentame", "hablame", "por que", "validarias", "revisarias", "que tal", "como lo ves", "que opinas", "vale la pena", "antes de avanzar"))


def _body_group(car: dict) -> str:
    body = _norm(car.get("body_type"))
    if body in {"pickup", "pick up", "truck"}: return "utility"
    if body in {"suv", "crossover"}: return "suv"
    if body in {"sedan", "hatchback", "coupe", "wagon"}: return "passenger"
    return body or "unknown"


def _checks(car: dict) -> list[str]:
    checks = []
    km = _num(car.get("km")); year = _num(car.get("year"))
    if km is None:
        checks.append("kilometraje real")
    elif year and year >= 2022 and km <= 30000:
        checks.append("consistencia del kilometraje con historial y mantenimiento")
    elif km >= 100000:
        checks.append("desgaste y mantenimiento acumulado")
    checks.append("documentos e identificadores del vehículo")
    checks.append("historial de daños y condición física/mecánica")
    return checks[:3]


def _guidance(car: dict) -> dict:
    g = model_guidance(car)
    pros = str(g.get("pros") or "puede encajar por sus números y disponibilidad")
    cons = str(g.get("cons") or "la unidad todavía debe demostrar condición e historial")
    cons = re.sub(r"\bAlto\b|\bPicanto\b|\bMirage\b", "alternativas urbanas más pequeñas", cons, flags=re.I)
    cons = re.sub(r"(?:alternativas urbanas más pequeñas\s*,\s*)+", "alternativas urbanas más pequeñas, ", cons)
    return {"pros": pros, "cons": cons}


def _vehicle_brief(body) -> dict | None:
    if body is None:
        return None
    latest = _latest(body)
    if not _is_vehicle_brief(latest):
        return None
    shown = _unique(list(getattr(body, "shown_cars", None) or []))
    if not shown:
        return None
    focus = _focus(latest, shown)
    if focus is None:
        return None
    profile = _profile(body, shown)
    peers = [c for c in shown if _body_group(c) == _body_group(focus)] or [focus]
    ranked = sorted(peers, key=lambda c: advisor_score(c, profile), reverse=True)
    pos = next((i + 1 for i, c in enumerate(ranked) if _key(c) == _key(focus)), None)
    leader = ranked[0] if ranked else focus

    facts = []
    year = _num(focus.get("year")); km = _num(focus.get("km")); monthly = _num(focus.get("monthly_est")); price = _num(focus.get("price_usd"))
    if year is not None: facts.append(str(int(year)))
    if km is not None: facts.append(f"{km:,.0f} km reportados")
    if monthly is not None: facts.append(f"~${monthly:,.0f}/mes")
    elif price is not None: facts.append(f"${price:,.0f} publicados")

    if pos == 1:
        reading = f"Entre las alternativas comparables visibles, el {_name(focus)} es el que investigaría primero."
    else:
        reading = f"Hoy lo tengo #{pos or '—'} entre las alternativas comparables."
        if _key(leader) != _key(focus):
            reading += f" Pondría antes al {_name(leader)} por mejor ajuste global con los datos disponibles."

    g = _guidance(focus)
    sections = [
        {"title":"Mi lectura", "text":reading},
        {"title":"Por qué", "text":f"{'; '.join(facts[:3]) or 'Sus datos visibles encajan con la búsqueda'}. {g['pros'].capitalize()}."},
        {"title":"Trade-off", "text":g["cons"].capitalize().rstrip(".") + "."},
        {"title":"CarTrade se encarga", "text":(
            "Tú no tienes que encargarte de estas verificaciones. CarTrade revisa " + "; ".join(_checks(focus)) + ", y coordina la inspección aplicable antes de que avances. "
            "Si la unidad pasa los checks, CarTrade te acompaña con financiamiento, contrato, pago protegido, traspaso y entrega. Si algo importante no cuadra, te lo mostramos antes de comprometerte."
        )},
    ]
    reply = "\n\n".join(f"**{s['title'].upper()}** · {s['text']}" for s in sections)
    return {"phase":"conversation", "reply":reply, "response_sections":sections, "focus_vehicle":focus, "cartrade_execution_owner":True, "verification_status":"pending", "clear_recommendations":False, "token_path":"deterministic_vehicle_brief_v18", "advisor_mode":"cartrade_execution_brief_v18", "llm_calls":0}


def _invariants(result: Any) -> Any:
    if not isinstance(result, dict) or result.get("phase") != "recommendation":
        return result
    featured = _unique(list(result.get("recommendations") or []))
    secondary = _unique(list(result.get("explore") or []))
    loaded = _unique(list(result.get("loaded_options") or []) or (featured + secondary))
    market = int(result.get("market_pool_size") or result.get("pool_size") or 0)
    raw_eligible = result.get("eligible_option_count")
    if raw_eligible is None: raw_eligible = result.get("quality_candidate_count")
    try: eligible = max(len(loaded), int(raw_eligible or len(loaded)))
    except Exception: eligible = len(loaded)
    remaining = max(0, eligible - len(loaded))
    batch = min(_MAX_PAGE, remaining)
    result.update({
        "loaded_options":loaded,
        "loaded_option_ids":[_key(c) for c in loaded],
        "loaded_option_count":len(loaded),
        "market_pool_size":market,
        "eligible_option_count":eligible,
        "remaining_option_count":remaining,
        "more_options_available":remaining > 0,
        "more_options_count":remaining,
        "more_options_batch_size":batch,
        "more_options_cta":f"Ver {batch} más" if batch else None,
        "market_count_label":"vehículos analizados",
        "eligible_count_label":"opciones que cumplen tus criterios",
        "count_semantics_version":"v18",
    })
    if result.get("token_path") in {"deterministic_continuation", "deterministic_dynamic_preference"}:
        result["reply"] = f"Encontré {len(loaded)} opciones adicionales que mantienen tus criterios y no repiten las anteriores." + (f" Quedan {remaining} más que todavía pasan el filtro." if remaining else " Estas son las últimas que pasan el filtro actual.")
        result["llm_calls"] = 0
    return result


def _patch() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat": continue
        prior = getattr(route, "endpoint", None); dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None: continue
        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = commercial._request_body(args, kwargs)
            brief = _vehicle_brief(body)
            if brief is not None: return brief
            return _invariants(__prior(*args, **kwargs))
        route.endpoint = endpoint; dependant.call = endpoint; break

_patch()
