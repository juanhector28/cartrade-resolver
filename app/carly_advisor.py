"""Deterministic recommendation intelligence for Carly.

Zero LLM tokens: structured buyer/profile + listing data become a relative
recommendation score, distinct card thesis and richer post-shortlist advice.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def _norm(value: Any) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


_CITY_HATCH = re.compile(
    r"\b(?:picanto|alto|swift|mirage|spark|fit|jazz|march|micra|i10|grand i10|"
    r"atos|celerio|up|polo|fabia|fiesta|mazda 2|yaris hatch|rio hatch)\b", re.I,
)
_MPV = re.compile(
    r"\b(?:c max|cmax|c-max|b max|bmax|b-max|touran|scenic|picasso|zafira|"
    r"carens|rondo|prius v|verso|freed|stream)\b", re.I,
)


def semantic_class(car: dict) -> str:
    blob = _norm(" ".join(str(car.get(k) or "") for k in ("make", "model")))
    body = _norm(car.get("body_type"))
    if _MPV.search(blob):
        return "mpv"
    if _CITY_HATCH.search(blob):
        return "city_hatch"
    if body == "hatchback":
        return "compact_hatch"
    if body == "sedan":
        return "sedan"
    return body or "vehicle"


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def advisor_score(car: dict, profile: Any) -> float:
    """Mission-relative score, not a universal vehicle score."""
    score = 50.0
    job = getattr(profile, "primary_job", None)
    cls = semantic_class(car)
    body = _norm(car.get("body_type"))

    if job == "city_runabout":
        score += {"city_hatch": 18, "compact_hatch": 13, "sedan": 5, "mpv": -24}.get(cls, -8)
        if body == "hatchback": score += 7
        elif body == "sedan": score += 1

    year = _num(car.get("year"))
    if year is not None:
        if year >= 2022: score += 10
        elif year >= 2019: score += 7
        elif year >= 2016: score += 3
        else: score -= 2

    km = _num(car.get("km"))
    if km is not None:
        if km <= 40000: score += 9
        elif km <= 80000: score += 6
        elif km <= 120000: score += 2
        else: score -= 5

    monthly = _num(car.get("monthly_est"))
    ceiling = _num(getattr(profile, "max_monthly", None))
    if monthly is not None and ceiling and ceiling > 0:
        ratio = monthly / ceiling
        if ratio <= .40: score += 8
        elif ratio <= .60: score += 6
        elif ratio <= .80: score += 3
        elif ratio <= 1.0: score += 1
        else: score -= 20

    delta = _num(car.get("value_delta_pct"))
    if delta is not None:
        if delta <= 0: score += 5
        elif delta <= 5: score += 3
        elif delta <= 10: score += 1
        else: score -= 3

    return round(max(0.0, min(100.0, score)), 1)


def _name(car: dict) -> str:
    return " ".join(str(x) for x in (car.get("make"), car.get("model"), car.get("year")) if x).strip() or "esta unidad"


def advisor_snapshot(car: dict, profile: Any, rank: int | None = None) -> dict:
    score = advisor_score(car, profile)
    monthly = _num(car.get("monthly_est"))
    ceiling = _num(getattr(profile, "max_monthly", None))
    km = _num(car.get("km"))
    year = _num(car.get("year"))
    cls = semantic_class(car)
    reasons: list[str] = []
    tradeoffs: list[str] = []

    if getattr(profile, "primary_job", None) == "city_runabout":
        if cls == "city_hatch": reasons.append("formato especialmente práctico para ciudad y estacionamiento")
        elif cls == "compact_hatch": reasons.append("formato hatchback adecuado para ciudad")
        elif cls == "sedan": tradeoffs.append("es menos compacto que los hatchback finalistas")
    if monthly is not None and ceiling:
        reasons.append(f"deja aproximadamente ${max(0.0, ceiling-monthly):,.0f}/mes de margen frente a tu techo")
    if year is not None and year >= 2020:
        reasons.append(f"es relativamente reciente ({int(year)})")
    if km is not None:
        if km <= 50000: reasons.append(f"reporta {km:,.0f} km, bajo frente a varias alternativas")
        elif km >= 120000: tradeoffs.append(f"reporta {km:,.0f} km, así que el kilometraje pesa en contra")
        elif km >= 80000: tradeoffs.append(f"reporta {km:,.0f} km, un punto a revisar frente a opciones con menos uso")
    delta = _num(car.get("value_delta_pct"))
    if delta is not None:
        if delta <= 0: reasons.append("el precio está bien posicionado frente a comparables")
        elif delta >= 8: tradeoffs.append("el precio luce alto frente a comparables y convendría negociar")
    if not tradeoffs:
        tradeoffs.append("estado real, historial y documentos todavía deben verificarse")

    label = {1:"Mi favorita para tu caso",2:"Mi segunda opción",3:"La alternativa que mantendría"}.get(rank, "Opción a considerar")
    return {
        "score": score,
        "semantic_class": cls,
        "position": rank,
        "label": label,
        "reasons": reasons[:3],
        "tradeoffs": tradeoffs[:2],
        "unknowns": ["condición mecánica", "historial", "documentos", "términos finales de financiamiento"],
    }


def curate(cards: list[dict], profile: Any, limit: int = 3, threshold: float = 58.0) -> tuple[list[dict], list[dict]]:
    unique: list[dict] = []
    seen = set()
    for card in cards or []:
        key = card.get("url") or card.get("id") or (_norm(card.get("make")), _norm(card.get("model")), card.get("year"), card.get("price_usd"))
        if key in seen: continue
        seen.add(key); unique.append(dict(card))
    ranked = sorted(unique, key=lambda c: advisor_score(c, profile), reverse=True)
    strong = [c for c in ranked if advisor_score(c, profile) >= threshold][:limit]
    if not strong and ranked: strong = ranked[:1]
    strong_keys = {c.get("url") or c.get("id") or (_norm(c.get("make")),_norm(c.get("model")),c.get("year"),c.get("price_usd")) for c in strong}
    rest = [c for c in ranked if (c.get("url") or c.get("id") or (_norm(c.get("make")),_norm(c.get("model")),c.get("year"),c.get("price_usd"))) not in strong_keys]
    for idx, card in enumerate(strong, 1):
        snap = advisor_snapshot(card, profile, idx)
        card["advisor_snapshot"] = snap; card["advisor_score"] = snap["score"]
        card["best_for"] = snap["label"]; card["strategy_label"] = snap["label"]
        card["advisor_reason"] = "; ".join(snap["reasons"][:2]); card["advisor_tradeoff"] = snap["tradeoffs"][0]
    for card in rest:
        snap = advisor_snapshot(card, profile, None); card["advisor_snapshot"] = snap; card["advisor_score"] = snap["score"]
    return strong, rest


def _find_focus(latest: str, visible: list[dict]) -> dict | None:
    text = _norm(latest)
    for car in visible or []:
        model = _norm(car.get("model")); make = _norm(car.get("make"))
        if model and model in text: return car
        if make and len(make) > 2 and make in text: return car
    return None


def rich_followup(latest: str, visible: list[dict], profile: Any) -> str | None:
    n = _norm(latest)
    triggers = ("cuentame mas","que piensas","que opinas","por que","preocupa","preocupar","deberia saber","vale la pena","comprarias","elegirias")
    if not any(t in n for t in triggers): return None
    ranked = sorted(list(visible or []), key=lambda c: advisor_score(c, profile), reverse=True)
    focus = _find_focus(latest, visible)
    if focus is None:
        if any(t in n for t in ("cual comprarias","cual elegirias","por cual")) and ranked: focus = ranked[0]
        else: return None
    snap = advisor_snapshot(focus, profile); name = _name(focus)
    pos = next((i+1 for i,c in enumerate(ranked) if (c.get("url") and c.get("url")==focus.get("url")) or c is focus), None)
    opinion = "Sí lo consideraría seriamente."
    if pos == 1: opinion = "Sí. De las opciones que tienes enfrente, es la que yo pondría primero."
    elif pos and pos > 3: opinion = "Lo consideraría, pero no sería mi primera elección entre las opciones que ya tienes."
    reasons = "; ".join(snap["reasons"][:3]) or "sus números encajan razonablemente con tu búsqueda"
    trade = snap["tradeoffs"][0]
    compare = ""
    if ranked:
        leader = ranked[0]
        same = (leader.get("url") and leader.get("url")==focus.get("url")) or leader is focus
        if not same: compare = f" Yo pondría por delante al {_name(leader)} porque su ajuste global a tu misión sale mejor con los datos disponibles."
        elif len(ranked)>1: compare = f" Su rival más cercano en esta ronda sería el {_name(ranked[1])}."
    return f"{opinion} Mi lectura del {name}: {reasons}. El trade-off principal es que {trade}." + compare + " Antes de comprarlo, validaría condición mecánica, historial, documentos y las condiciones finales de financiamiento."
