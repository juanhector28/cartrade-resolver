"""Carly v14: deterministic comparative advisor intelligence.

Fixes vehicle-detail follow-ups without adding LLM calls. Carly now explains a
unit relative to the other visible candidates, avoids self-comparisons, keeps a
stable ranking, and turns listing-specific unknowns into verification priorities.
"""
from __future__ import annotations

import re
import unicodedata
from types import SimpleNamespace
from typing import Any

from . import main_v13 as v13
from .carly_advisor import advisor_score, semantic_class
from .carly_vehicle_brief import model_guidance

app = v13.app
commercial = v13.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v14-comparative-advisor-zero-token"


def _norm(value: Any) -> str:
    s = unicodedata.normalize("NFKD", str(value or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _name(car: dict) -> str:
    return " ".join(str(x) for x in (car.get("make"), car.get("model"), car.get("year")) if x).strip() or "esta unidad"


def _key(car: dict):
    return car.get("url") or car.get("id") or (_norm(car.get("make")), _norm(car.get("model")), car.get("year"), car.get("price_usd"), car.get("km"))


def _unique(rows: list[dict]) -> list[dict]:
    out, seen = [], set()
    for car in rows:
        if not isinstance(car, dict):
            continue
        key = _key(car)
        if key in seen:
            continue
        seen.add(key); out.append(car)
    return out


def _latest(body) -> str:
    try:
        return v13.v12.v11.v10._latest_user(body)
    except Exception:
        return ""


def _focus(latest: str, visible: list[dict]) -> dict | None:
    text = _norm(latest)
    # Model match first. Make-only matching is too ambiguous when several units
    # share a brand.
    for car in visible:
        model = _norm(car.get("model"))
        if model and model in text:
            year = str(car.get("year") or "")
            if not year or year in text or sum(_norm(c.get("model")) == model for c in visible) == 1:
                return car
    for car in visible:
        make = _norm(car.get("make"))
        if make and len(make) > 2 and make in text and sum(_norm(c.get("make")) == make for c in visible) == 1:
            return car
    return None


def _profile(body, visible: list[dict]):
    try:
        p = v13.v12.v11._profile_for_brief(body, visible)
        if p is not None:
            return p
    except Exception:
        pass
    # Safe fallback for an explicitly city-shaped visible set. This only affects
    # relative scoring and never invents vehicle facts.
    cityish = sum(semantic_class(c) in {"city_hatch", "compact_hatch", "sedan"} for c in visible)
    if visible and cityish >= max(1, (len(visible) + 1) // 2):
        return SimpleNamespace(primary_job="city_runabout", max_monthly=None, prefer_body=[], require_body=[])
    return SimpleNamespace(primary_job=None, max_monthly=None, prefer_body=[], require_body=[])


def _specific_checks(car: dict) -> list[str]:
    checks: list[str] = []
    km = _num(car.get("km")); year = _num(car.get("year")); price = _num(car.get("price_usd"))
    if km is None:
        checks.append("kilometraje real, porque no está confirmado en la ficha")
    elif year and year >= 2022 and km <= 30000:
        checks.append("que el kilometraje reportado sea consistente con historial y mantenimiento")
    elif km >= 100000:
        checks.append("desgaste mecánico y mantenimiento acumulado por el kilometraje")
    if not car.get("vin") and not car.get("chassis"):
        checks.append("VIN/chasis y su consistencia con registro y unidad física")
    if not car.get("history_status"):
        checks.append("historial de accidentes, reparaciones estructurales y mantenimiento disponible")
    if price is not None:
        checks.append("que precio, disponibilidad y condiciones publicadas sigan vigentes")
    checks.append("titularidad, restricciones de transferencia y condición física/mecánica")
    return checks[:3]


def _relative_sentence(focus: dict, ranked: list[dict], pos: int | None) -> str:
    if not ranked or pos is None:
        return "Lo mantendría como candidato, pero la unidad todavía tiene que ganarse la recomendación con la verificación."
    if pos == 1:
        if len(ranked) == 1:
            return "Lo investigaría, pero no lo llamaría mi favorito sin una alternativa comparable enfrente."
        rival = ranked[1]
        return f"Con los datos visibles hoy lo tengo primero, por delante del {_name(rival)}; esa ventaja sigue condicionada a verificar la unidad."
    leader = ranked[0]
    return f"Hoy lo tengo #{pos}; pondría primero al {_name(leader)} por mejor ajuste global con los datos disponibles."


def _value_comparison(focus: dict, ranked: list[dict]) -> str:
    fp = _num(focus.get("price_usd")); fy = _num(focus.get("year"))
    if fp is None or fy is None:
        return ""
    best = None
    for other in ranked:
        if _key(other) == _key(focus):
            continue
        op = _num(other.get("price_usd")); oy = _num(other.get("year"))
        if op is None or oy is None:
            continue
        gap = fp - op
        year_gap = fy - oy
        if abs(gap) <= 1000 and abs(year_gap) >= 2:
            best = (other, gap, year_gap); break
    if not best:
        return ""
    other, gap, year_gap = best
    if year_gap > 0:
        return f"Frente al {_name(other)}, cuesta ${abs(gap):,.0f} {'más' if gap > 0 else 'menos'} pero es {abs(int(year_gap))} años más reciente; esa diferencia de edad pesa a su favor."
    return f"Frente al {_name(other)}, cuesta ${abs(gap):,.0f} {'más' if gap > 0 else 'menos'} pero es {abs(int(year_gap))} años más antiguo; necesitaría justificarlo con mejor condición, kilometraje o equipamiento."


def _advisor_brief(body) -> dict | None:
    if body is None:
        return None
    latest = _latest(body)
    n = _norm(latest)
    if not any(x in n for x in ("cuentame", "por que", "recomiendas", "validar", "validaria", "revisar", "que tal", "como lo ves", "que opinas")):
        return None
    visible = _unique(list(getattr(body, "shown_cars", None) or []))
    if not visible:
        return None
    focus = _focus(latest, visible)
    if focus is None:
        return None
    profile = _profile(body, visible)
    ranked = sorted(visible, key=lambda c: advisor_score(c, profile), reverse=True)
    pos = next((i + 1 for i, c in enumerate(ranked) if _key(c) == _key(focus)), None)
    guidance = model_guidance(focus)
    facts = []
    year = _num(focus.get("year")); km = _num(focus.get("km")); monthly = _num(focus.get("monthly_est")); price = _num(focus.get("price_usd"))
    if year: facts.append(str(int(year)))
    if km is not None: facts.append(f"{km:,.0f} km reportados")
    if monthly is not None: facts.append(f"~${monthly:,.0f}/mes")
    elif price is not None: facts.append(f"${price:,.0f} publicados")
    why = "; ".join(facts[:3]) or "sus datos visibles encajan razonablemente con la búsqueda"
    relative = _relative_sentence(focus, ranked, pos)
    value = _value_comparison(focus, ranked)
    checks = _specific_checks(focus)
    sections = [
        {"title": "Mi lectura", "text": relative},
        {"title": "Por qué", "text": f"{why}. {guidance['pros'].capitalize()}." + (f" {value}" if value else "")},
        {"title": "Trade-off", "text": guidance["cons"].capitalize() + "."},
        {"title": "Antes de avanzar", "text": "Validaría " + "; ".join(checks) + ". Hasta entonces, la unidad sigue pendiente, no confirmada."},
    ]
    reply = "\n\n".join(f"**{s['title'].upper()}** · {s['text']}" for s in sections)
    return {"phase":"conversation", "reply":reply, "response_sections":sections, "token_path":"deterministic_comparative_advisor", "advisor_mode":"comparative_vehicle_brief_v14", "llm_calls":0, "clear_recommendations":False}


def _patch() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None); dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None:
            continue
        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = commercial._request_body(args, kwargs)
            direct = _advisor_brief(body)
            if direct is not None:
                return direct
            return __prior(*args, **kwargs)
        route.endpoint = endpoint; dependant.call = endpoint; break

_patch()
