"""Carly v56: decisive unit-level "is this a good buy?" advice.

Model intelligence, unit assessment and shortlist continuation are different jobs.
This layer gives explicit purchase-decision questions outer precedence and combines
model fit, concrete unit facts, market positioning and buyer fit. Verification-
pending facts remain pending.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from functools import wraps
from typing import Any

from . import carly_v52_hotfix as v52
from . import carly_v55_model_intelligence as v55
from . import main_v14 as v14
from . import main_v50 as v50

log = logging.getLogger("carly.v56")

_BUY_RE = re.compile(
    r"(?:\bbuena\s+compra\b|\bvale\s+la\s+pena\s+(?:comprar(?:lo|la)?|esta|este)?\b|"
    r"\b(?:lo|la)\s+comprarias\b|\bcomprarias\s+(?:este|esta|ese|esa)\b|"
    r"\bme\s+conviene\s+(?:comprar(?:lo|la)?|este|esta)?\b|"
    r"\bdeberia\s+comprar(?:lo|la)?\b|\bes\s+(?:este|esta)\s+una\s+buena\s+compra\b)",
    re.I,
)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _key(car: dict) -> tuple:
    return (
        car.get("url") or car.get("id"),
        v14._norm(car.get("make")),
        v14._norm(car.get("model")),
        car.get("year"),
        car.get("price_usd"),
    )


def _name(car: dict) -> str:
    return " ".join(str(x) for x in (car.get("make"), car.get("model"), car.get("year")) if x).strip() or "esta unidad"


def _unique(cars: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen = set()
    for car in cars:
        k = _key(car)
        if k not in seen:
            seen.add(k)
            out.append(car)
    return out


def _latest_buyer(body: Any) -> str:
    return v55._latest_buyer_text(body)


def _is_buy_decision(body: Any) -> bool:
    shown = list(_get(body, "shown_cars", []) or [])
    latest = v14._norm(_latest_buyer(body))
    return bool(shown and latest and _BUY_RE.search(latest))


def _recent_focus(body: Any, visible: list[dict]) -> dict | None:
    """Resolve the unit named now, or the last unambiguous unit discussed.

    Year-specific mentions win. A model-only mention is accepted only when that
    model identifies exactly one visible unit. This avoids confusing two HR-Vs
    from different years when the next buyer turn says only "esta unidad".
    """
    latest = _latest_buyer(body)
    focus = v14._focus(latest, visible)
    if focus is not None:
        return focus
    if len(visible) == 1:
        return visible[0]

    messages = list(_get(body, "messages", []) or [])
    for message in reversed(messages[:-1]):
        text = str(_get(message, "content", "") or "")
        n = v14._norm(text)

        exact_year: list[dict] = []
        for car in visible:
            model = v14._norm(car.get("model"))
            year = str(car.get("year") or "")
            if model and model in n and year and year in text:
                exact_year.append(car)
        exact_year = _unique(exact_year)
        if len(exact_year) == 1:
            return exact_year[0]

        by_model: dict[str, list[dict]] = {}
        for car in visible:
            model = v14._norm(car.get("model"))
            if model:
                by_model.setdefault(model, []).append(car)
        model_only = [cars[0] for model, cars in by_model.items() if model in n and len(cars) == 1]
        model_only = _unique(model_only)
        if len(model_only) == 1:
            return model_only[0]
    return None


def _profile(body: Any, visible: list[dict]):
    try:
        return v14._profile(body, visible)
    except Exception:
        return None


def _monthly_ceiling(profile: Any) -> float | None:
    if profile is None:
        return None
    return _num(profile.get("max_monthly") if isinstance(profile, dict) else getattr(profile, "max_monthly", None))


def _ranked(visible: list[dict], profile: Any) -> list[dict]:
    if profile is None:
        return list(visible)
    return sorted(list(visible), key=lambda car: v14.advisor_score(car, profile), reverse=True)


def _rank_of(focus: dict, ranked: list[dict]) -> int | None:
    fk = _key(focus)
    for i, car in enumerate(ranked, 1):
        if _key(car) == fk:
            return i
    return None


def _market_read(car: dict) -> tuple[str, str]:
    delta = _num(car.get("value_delta_pct"))
    label = str(car.get("value_label") or "").strip()
    if delta is not None:
        if delta <= 0:
            position = "por debajo" if delta < 0 else "en línea"
            return "favorable", f"El precio está bien posicionado frente a comparables ({abs(delta):.0f}% {position} del benchmark reportado)."
        if delta <= 5:
            return "fair", f"El precio está razonablemente en línea con comparables; el diferencial reportado es de ~{delta:.0f}%."
        if delta <= 10:
            return "soft_high", f"El precio luce algo alto frente a comparables (~{delta:.0f}%); la compraría solo si condición/equipamiento justifican esa prima."
        return "high", f"El precio luce caro frente a comparables (~{delta:.0f}% arriba); no la llamaría buena compra a este precio sin una razón muy clara."
    if label:
        return "label", f"La señal de mercado disponible la clasifica como: {label}."
    return "unknown", "No tengo un benchmark de mercado suficientemente firme para llamarla ganga o cara solo por precio."


def _unit_read(car: dict) -> tuple[list[str], list[str]]:
    positives: list[str] = []
    cautions: list[str] = []
    year = _num(car.get("year"))
    km = _num(car.get("km"))
    monthly = _num(car.get("monthly_est"))
    price = _num(car.get("price_usd"))
    current_year = datetime.now(timezone.utc).year

    if monthly is not None:
        positives.append(f"cuota estimada de ~${monthly:,.0f}/mes")
    elif price is not None:
        positives.append(f"precio publicado de USD {price:,.0f}")

    if year is not None and km is not None:
        if year <= current_year - 1 and km < 1000:
            cautions.append(
                f"los {km:,.0f} km reportados son inusualmente bajos para un {int(year)}; no los usaría como ventaja hasta confirmar el dato"
            )
        elif km <= 50000:
            positives.append(f"{km:,.0f} km reportados, relativamente bajos")
        elif km >= 120000:
            cautions.append(f"{km:,.0f} km reportados, que elevan la importancia del historial y mantenimiento")
        elif km >= 80000:
            cautions.append(f"{km:,.0f} km reportados, un uso que compararía contra alternativas más frescas")
    return positives[:2], cautions[:2]


def _safe_model_guidance(car: dict) -> tuple[str, str]:
    pro, con = v52._model_guidance(car)
    if "precio y disponibilidad" in v14._norm(pro):
        pro = ""
    if "necesita mas evidencia antes de saber" in v14._norm(con):
        con = ""
    return pro, con


def _verdict(focus: dict, profile: Any, rank: int | None, market_state: str, score: float | None) -> str:
    monthly = _num(focus.get("monthly_est"))
    ceiling = _monthly_ceiling(profile)
    if monthly is not None and ceiling is not None and monthly > ceiling:
        return "No con esta estructura. La unidad puede gustarme, pero queda por encima de tu techo mensual."
    if market_state == "high":
        return "No a este precio. Puede ser una buena unidad, pero el precio actual no me deja llamarla una buena compra."
    if score is not None and score >= 75 and market_state in {"favorable", "fair", "label", "unknown"}:
        return "Sí, la mantendría como una buena compra potencial, pendiente de verificar esta unidad concreta."
    if score is not None and score >= 65:
        return "Sí la consideraría, pero como compra razonable, no como ganga."
    if rank is not None and rank > 1:
        return "No sería mi primera compra entre tus finalistas actuales."
    return "Todavía no tengo evidencia suficiente para llamarla una buena compra con convicción."


def buy_decision(body: Any) -> dict | None:
    if not _is_buy_decision(body):
        return None
    visible = v14._unique(list(_get(body, "shown_cars", []) or []))
    focus = _recent_focus(body, visible)
    if focus is None:
        return {
            "phase": "conversation",
            "reply": "Puedo darte un veredicto, pero necesito saber cuál de las unidades visibles estás evaluando. Dime el modelo o toca esa tarjeta y la juzgo contra tu shortlist.",
            "route_precedence": "buy_decision_v56",
            "buyer_decision": True,
            "llm_calls": 0,
        }

    profile = _profile(body, visible)
    ranked = _ranked(visible, profile)
    rank = _rank_of(focus, ranked)
    score = v14.advisor_score(focus, profile) if profile is not None else None
    market_state, market_text = _market_read(focus)
    positives, cautions = _unit_read(focus)
    model_pro, model_con = _safe_model_guidance(focus)
    name = _name(focus)
    ceiling = _monthly_ceiling(profile)
    monthly = _num(focus.get("monthly_est"))

    fit_bits: list[str] = []
    if score is not None:
        if score >= 75:
            fit_bits.append("encaja fuerte con tu búsqueda")
        elif score >= 65:
            fit_bits.append("encaja razonablemente con tu búsqueda")
        else:
            fit_bits.append("su ajuste a tu búsqueda es más débil que el de otros finalistas")
    if monthly is not None and ceiling is not None:
        if monthly <= ceiling:
            fit_bits.append(f"deja ~${max(0.0, ceiling-monthly):,.0f}/mes de margen frente a tu techo")
        else:
            fit_bits.append(f"se pasa ~${monthly-ceiling:,.0f}/mes de tu techo")

    unit_text = "; ".join(positives) if positives else "los datos visibles no muestran todavía una ventaja clara de unidad"
    caution_bits = list(cautions)
    if model_con:
        caution_bits.append(model_con.rstrip(". "))
    if not caution_bits:
        caution_bits.append("condición real, historial y documentos siguen pendientes de verificación")

    compare = ""
    if ranked:
        leader = ranked[0]
        if _key(leader) != _key(focus):
            compare = f"Entre tus opciones visibles, yo pondría antes al {_name(leader)} por mejor ajuste global con los datos actuales."
        elif len(ranked) > 1:
            compare = f"Hoy está arriba de tu shortlist; su rival más cercano es el {_name(ranked[1])}."

    verdict = _verdict(focus, profile, rank, market_state, score)
    why_parts = [p for p in (model_pro.rstrip(". ") if model_pro else "", unit_text, market_text, "; ".join(fit_bits)) if p]
    risk = ". ".join(x.rstrip(". ") for x in caution_bits[:2]) + "."
    change = (
        "Mi veredicto cambiaría si la verificación contradice kilometraje/estado/historial, "
        "si el precio final se mueve materialmente o si aparece un comparable claramente mejor."
    )

    sections = [
        {"title": "Veredicto", "text": verdict},
        {"title": "Por qué", "text": ". ".join(why_parts[:4]).rstrip(". ") + "."},
        {"title": "Lo que me frena", "text": risk},
    ]
    if compare:
        sections.append({"title": "Contra tus finalistas", "text": compare})
    sections.append({"title": "Qué cambiaría mi opinión", "text": change})
    reply = "\n\n".join(f"{s['title'].upper()}\n{s['text']}" for s in sections)
    return {
        "phase": "conversation",
        "reply": reply,
        "sections": sections,
        "focus": name,
        "advisor_score": score,
        "shortlist_rank": rank,
        "market_state": market_state,
        "route_precedence": "buy_decision_v56",
        "buyer_decision": True,
        "llm_calls": 0,
    }


def install(app: Any) -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None or getattr(prior, "_carly_v56_buy_decision", False):
            continue

        @wraps(prior)
        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = v50.v47.commercial._request_body(args, kwargs)
            direct = buy_decision(body)
            if direct is not None:
                return direct
            return __prior(*args, **kwargs)

        endpoint._carly_v56_buy_decision = True
        endpoint._carly_v56_prior = prior
        route.endpoint = endpoint
        dependant.call = endpoint
        log.warning("CARLY_V56 installed buy_decision_precedence=true")
        return
