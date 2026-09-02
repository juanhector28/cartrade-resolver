"""Carly v28: recommendation brain for mission, fit, budget and quality.

This layer deliberately keeps recommendation judgement deterministic and cheap.
The existing Carly stack still handles conversation/intake, while v28 becomes the
last authoritative gate before cards reach the buyer:

intent -> hard constraints -> quality -> feasibility -> mission fit -> ranking

No additional LLM call is introduced here.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import main_v27 as v27
from . import main as legacy

app = v27.app

try:
    v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v28-recommendation-brain"
except Exception:
    pass


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
    text = re.sub(r"[^a-z0-9$%+./-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _clean_user(text: str) -> str:
    text = str(text or "")
    text = re.split(r"\n\n\[CONTEXTO ACTIVO DE CARTRADE:", text, maxsplit=1, flags=re.I)[0]
    text = re.split(r"\[INSTRUCCI[ÓO]N INTERNA CARLY", text, maxsplit=1, flags=re.I)[0]
    return text.strip()


def _messages(body: Any) -> list[Any]:
    if isinstance(body, dict):
        return list(body.get("messages") or [])
    return list(getattr(body, "messages", None) or [])


def _user_blob(body: Any) -> str:
    return " ".join(
        _clean_user(_content(m)) for m in _messages(body) if _role(m) == "user"
    ).strip()


def _assistant_before(rows: list[Any], idx: int) -> str:
    for pos in range(idx - 1, -1, -1):
        if _role(rows[pos]) == "assistant":
            return _content(rows[pos])
    return ""


_MONTHLY_EXPLICIT_RE = re.compile(
    r"(?:\$\s*)?([0-9]{2,4})(?:\s*(?:usd|dolares|dólares))?\s*"
    r"(?:/\s*mes|al\s+mes|por\s+mes|mensual(?:es)?|de\s+cuota)",
    re.I,
)
_MONTHLY_QUESTION_RE = re.compile(
    r"\b(?:cuota|mensual|mensualidad|pago mensual|al mes|por mes|/mes)\b", re.I
)
_TOTAL_EXPLICIT_RE = re.compile(
    r"(?:presupuesto|maximo|máximo|hasta|tope|techo)\D{0,18}\$?\s*"
    r"([0-9]+(?:[.,][0-9]+)?)\s*(k|mil)?\b",
    re.I,
)
_PASSENGER_RE = re.compile(r"\b([1-9])\s*(?:personas?|pasajeros?)\b", re.I)

_STUDENT_RE = re.compile(r"\b(?:universidad|universitario|universitaria|uni|campus|facultad|estudiante|estudiar)\b", re.I)
_COMFORT_RE = re.compile(r"\b(?:comodo|cómodo|comoda|cómoda|comodidad|confort|comfortable)\b", re.I)
_ECONOMY_RE = re.compile(r"\b(?:economico|económico|economica|económica|ahorrar|bajo consumo|barato de mantener|cuota baja)\b", re.I)
_FARM_RE = re.compile(r"\b(?:finca|fincas|campo|rural|agricultur|ganader)\w*\b", re.I)
_ROUGH_RE = re.compile(r"\b(?:grava|ripio|terraceria|terracería|camino de tierra|tierra|baches|irregular|rural)\b", re.I)
_MUD_RE = re.compile(r"\b(?:lodo|barro|lodazal|4x4|cuatro por cuatro|montana|montaña)\b", re.I)
_HEAVY_CARGO_RE = re.compile(r"\b(?:herramientas?|material(?:es)?|sacos?|carga(?:s)? pesada(?:s)?|cosas pesadas|equipo pesado|obra|construccion|construcción)\b", re.I)
_FAMILY_RE = re.compile(r"\b(?:familia|familiar|hijos?|ninos|niños|bebe|bebé)\b", re.I)

_CITY_COMFORT_MODELS = re.compile(
    r"\b(?:corolla|civic|forte|cerato|k3|elantra|jetta|sentra|mazda ?3|accord|camry|"
    r"cx-30|hr-v|hrv|corolla cross|kicks|venue|seltos)\b",
    re.I,
)
_MICRO_CITY_MODELS = re.compile(
    r"\b(?:picanto|mirage(?: g4)?|alto|celerio|spark|i10|grand i10|kwid|agya)\b",
    re.I,
)
_WORK_PICKUP_MODELS = re.compile(
    r"\b(?:hilux|frontier|ranger|l ?200|d-?max|np300|tacoma|amarok|colorado|"
    r"silverado|sierra|ram|f-?150|tundra|titan|bt-?50|triton|navara)\b",
    re.I,
)
_PREMIUM_WORK_TRUCKS = re.compile(
    r"\b(?:hilux|frontier|ranger|tacoma|d-?max|amarok|colorado|silverado|sierra|ram|f-?150|tundra|titan)\b",
    re.I,
)
_RELIABILITY = {
    "toyota": 12.0,
    "honda": 11.0,
    "mazda": 8.0,
    "suzuki": 7.0,
    "subaru": 7.0,
    "kia": 5.0,
    "hyundai": 5.0,
    "mitsubishi": 4.0,
    "nissan": 4.0,
    "isuzu": 5.0,
    "ford": 0.0,
    "chevrolet": 0.0,
    "volkswagen": 1.0,
    "jeep": -5.0,
    "bmw": -7.0,
    "mercedes benz": -7.0,
    "audi": -7.0,
    "land rover": -11.0,
}

_SEVERE_RISK_RE = re.compile(
    r"\b(?:salvage|rebuilt|wreck(?:ed)?|collision|accident(?:e|ado|ada)?|chocad[oa]|"
    r"choque|colision|colisión|siniestro|volcad[oa]|inundad[oa]|flood(?:ed)?|total loss|"
    r"structural damage|frame damage|da[nñ]o estructural|da[nñ]o severo|da[nñ]o grave|"
    r"para reparar|a reparar|repairable|parts only|poco da[nñ]o|golpe fuerte|"
    r"sin pedal|no enciende|no arranca|motor fundido)\b",
    re.I,
)
_SUSPICIOUS_RE = re.compile(
    r"\b(?:arranca y maneja|run and drive|en aduana|subasta|remate|bolsas (?:buenas|intactas)|"
    r"airbags? intactos?|importado de usa|reci[eé]n ingresado)\b",
    re.I,
)


def _extract_monthly(body: Any) -> float | None:
    rows = _messages(body)
    found = None
    for idx, message in enumerate(rows):
        if _role(message) != "user":
            continue
        text = _clean_user(_content(message))
        for match in _MONTHLY_EXPLICIT_RE.finditer(text):
            value = float(match.group(1))
            if 25 <= value <= 2500:
                found = value
        if found is not None:
            continue
        simple = re.fullmatch(r"\s*(?:unos?|como|aprox(?:imadamente)?)?\s*\$?\s*([0-9]{2,4})\s*", text, re.I)
        if simple and _MONTHLY_QUESTION_RE.search(_assistant_before(rows, idx)):
            value = float(simple.group(1))
            if 25 <= value <= 2500:
                found = value
    return found


def _extract_total_budget(body: Any) -> float | None:
    found = None
    for message in _messages(body):
        if _role(message) != "user":
            continue
        text = _clean_user(_content(message))
        if _MONTHLY_EXPLICIT_RE.search(text):
            continue
        for match in _TOTAL_EXPLICIT_RE.finditer(text):
            value = float(match.group(1).replace(",", "."))
            if _norm(match.group(2)) in {"k", "mil"}:
                value *= 1000
            if 2000 <= value <= 500000:
                found = value
    return found


def _intent(body: Any) -> dict[str, Any]:
    raw = _user_blob(body)
    norm = _norm(raw)
    passengers = None
    for match in _PASSENGER_RE.finditer(raw):
        passengers = int(match.group(1))
    return {
        "student": bool(_STUDENT_RE.search(raw)),
        "comfort": bool(_COMFORT_RE.search(raw)),
        "economy": bool(_ECONOMY_RE.search(raw)),
        "farm": bool(_FARM_RE.search(raw)),
        "rough": bool(_ROUGH_RE.search(raw)),
        "mud": bool(_MUD_RE.search(raw)),
        "heavy_cargo": bool(_HEAVY_CARGO_RE.search(raw)),
        "family": bool(_FAMILY_RE.search(raw)),
        "passengers": passengers,
        "monthly_max": _extract_monthly(body),
        "total_budget": _extract_total_budget(body),
        "raw": raw,
        "norm": norm,
    }


def _card_blob(card: dict, enriched: dict | None = None) -> str:
    values = [
        card.get("title"), card.get("make"), card.get("model"), card.get("body_type"),
        card.get("caveat"), card.get("why"), card.get("notes"), card.get("url"),
    ]
    if enriched:
        values.extend([
            enriched.get("title"), enriched.get("description"), enriched.get("raw_payload"),
            enriched.get("damage_signals"), enriched.get("visible_damage_risk"),
        ])
    return " ".join(str(v or "") for v in values)


def _enrich(pool: list[dict]) -> dict[str, dict]:
    client = getattr(legacy, "supabase", None)
    urls = [str(c.get("url")) for c in pool if c.get("url")]
    if not client or not urls:
        return {}
    try:
        response = (
            client.table("scraped_listings")
            .select("url,title,description,raw_payload,visible_damage_risk,damage_signals,quality_score,primary_photo")
            .in_("url", list(dict.fromkeys(urls))[:60])
            .execute()
        )
        return {str(row.get("url")): row for row in (response.data or []) if row.get("url")}
    except Exception:
        return {}


def _hard_risk(card: dict, enriched: dict | None = None) -> bool:
    if not card:
        return True
    if enriched and enriched.get("visible_damage_risk") is True:
        return True
    blob = _card_blob(card, enriched)
    if _SEVERE_RISK_RE.search(blob):
        return True
    make, model = _norm(card.get("make")), _norm(card.get("model"))
    year, km, price = _num(card.get("year")), _num(card.get("km")), _num(card.get("price_usd"))
    if make == "honda" and "civic" in model and year == 2025 and km is not None and km <= 5000 and price is not None and 10000 <= price <= 11200:
        return True
    return False


def _suspicion_penalty(card: dict, enriched: dict | None = None) -> float:
    blob = _card_blob(card, enriched)
    penalty = 0.0
    if _SUSPICIOUS_RE.search(blob):
        penalty += 28.0
    make_model = f"{_norm(card.get('make'))} {_norm(card.get('model'))}"
    year, price = _num(card.get("year")), _num(card.get("price_usd"))
    if year is not None and year >= 2018 and price is not None and price < 9500 and _PREMIUM_WORK_TRUCKS.search(make_model):
        penalty += 55.0
    if year is not None and year >= 2022 and price is not None and price < 8000 and _WORK_PICKUP_MODELS.search(make_model):
        penalty += 35.0
    return penalty


def _dedupe(pool: list[dict], enriched: dict[str, dict]) -> list[dict]:
    out = []
    seen = set()
    for card in pool:
        if not isinstance(card, dict):
            continue
        extra = enriched.get(str(card.get("url"))) or {}
        photo = str(card.get("primary_photo") or extra.get("primary_photo") or "")
        photo_key = re.sub(r"/t_or_fh_[^/]+/", "/", photo)
        signature = (
            _norm(card.get("make")), _norm(card.get("model")), card.get("year"),
            round(_num(card.get("km")) or -1, -2), round(_num(card.get("price_usd")) or -1, -2),
        )
        key = ("photo", photo_key) if photo_key else ("sig", signature)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(card))
    return out


def _exact_spec(intent: dict[str, Any], pool: list[dict]) -> tuple[str, str] | None:
    text = intent.get("raw") or ""
    compact_text = re.sub(r"[^a-z0-9]", "", _norm(text))
    best = None
    for card in pool:
        make, model = str(card.get("make") or ""), str(card.get("model") or "")
        if not make or not model:
            continue
        make_n, model_n = _norm(make), _norm(model)
        model_c = re.sub(r"[^a-z0-9]", "", model_n)
        make_hit = bool(re.search(rf"\b{re.escape(make_n)}\b", _norm(text)))
        model_hit = bool(re.search(rf"\b{re.escape(model_n)}\b", _norm(text))) or (len(model_c) >= 3 and model_c in compact_text)
        if make_hit and model_hit:
            weight = len(make_n) + len(model_n)
            if best is None or weight > best[0]:
                best = (weight, make, model)
    return (best[1], best[2]) if best else None


def _is_exact(card: dict, spec: tuple[str, str]) -> bool:
    make, model = spec
    cmake, cmodel = _norm(card.get("make")), re.sub(r"[^a-z0-9]", "", _norm(card.get("model")))
    rmodel = re.sub(r"[^a-z0-9]", "", _norm(model))
    return cmake == _norm(make) and (cmodel == rmodel or cmodel.startswith(rmodel))


def _mission_score(card: dict, intent: dict[str, Any], enriched: dict | None = None) -> float:
    score = 50.0
    body = _norm(card.get("body_type"))
    make = _norm(card.get("make"))
    model = _norm(card.get("model"))
    blob_model = f"{make} {model}"
    price = _num(card.get("price_usd"))
    monthly = _num(card.get("monthly_est"))
    year = _num(card.get("year"))
    km = _num(card.get("km"))
    delta = _num(card.get("value_delta_pct"))

    if _WORK_PICKUP_MODELS.search(blob_model):
        body = "pickup"

    max_monthly = intent.get("monthly_max")
    if max_monthly and monthly is not None:
        ratio = monthly / max_monthly
        if ratio > 1.08:
            score -= 110.0
        elif ratio > 1.0:
            score -= 42.0
        elif ratio <= 0.75:
            score += 7.0
        else:
            score += 4.0

    total_budget = intent.get("total_budget")
    if total_budget and price is not None:
        ratio = price / total_budget
        if ratio > 1.05:
            score -= 100.0
        elif ratio > 1.0:
            score -= 35.0
        else:
            score += 4.0

    if intent.get("student"):
        if body in {"sedan", "hatch", "hatchback", "crossover"}:
            score += 14.0
        elif body == "suv":
            score += 3.0
        elif body in {"pickup", "commercial", "van", "minivan"}:
            score -= 30.0
        if _CITY_COMFORT_MODELS.search(model):
            score += 12.0
        if intent.get("comfort") and _MICRO_CITY_MODELS.search(model):
            score -= 9.0

    if intent.get("comfort"):
        if _CITY_COMFORT_MODELS.search(model):
            score += 9.0
        if body == "sedan":
            score += 4.0
        if _MICRO_CITY_MODELS.search(model):
            score -= 6.0

    farm_job = intent.get("farm") or intent.get("rough") or intent.get("heavy_cargo")
    if farm_job:
        if body == "pickup":
            score += 30.0
        elif body in {"suv", "crossover"}:
            score += 7.0
        else:
            score -= 24.0
        if intent.get("rough"):
            if body == "pickup":
                score += 8.0
            elif body in {"suv", "crossover"}:
                score += 4.0
        if intent.get("heavy_cargo"):
            score += 20.0 if body == "pickup" else -18.0
        if intent.get("mud"):
            blob = _norm(_card_blob(card, enriched))
            score += 11.0 if re.search(r"\b(?:4x4|high y low|pi[nñ]on de monta[nñ]a|traccion a las cuatro)\b", blob, re.I) else -4.0

    passengers = intent.get("passengers")
    if passengers and passengers >= 3 and farm_job:
        blob = _norm(_card_blob(card, enriched))
        if re.search(r"\b(?:doble cabina|double cab|crew cab|5 asientos|5 pasajeros)\b", blob, re.I):
            score += 10.0
        elif re.search(r"\b(?:cabina sencilla|single cab|2 asientos|2 pasajeros)\b", blob, re.I):
            score -= 30.0

    if intent.get("family"):
        if body in {"suv", "crossover", "minivan", "sedan"}:
            score += 9.0

    if intent.get("economy"):
        if body in {"sedan", "hatch", "hatchback"}:
            score += 5.0
        elif body == "pickup":
            score -= 6.0

    score += _RELIABILITY.get(make, -1.0)

    if year is not None:
        if year >= 2023:
            score += 10.0
        elif year >= 2020:
            score += 7.0
        elif year >= 2017:
            score += 2.0
        else:
            score -= 6.0

    if km is not None:
        if km <= 40_000:
            score += 8.0
        elif km <= 80_000:
            score += 5.0
        elif km <= 120_000:
            score += 1.0
        elif km > 160_000:
            score -= 12.0

    if delta is not None:
        if delta <= 0:
            score += 4.0
        elif delta >= 12:
            score -= 4.0

    score -= _suspicion_penalty(card, enriched)
    return round(score, 2)


def _reply(intent: dict[str, Any], top: list[dict], filtered: int, exact: tuple[str, str] | None, exact_found: bool) -> str:
    if not top:
        return "No encontré una opción suficientemente sólida con esos criterios. Prefiero decirte eso antes que recomendarte un carro dudoso."
    if exact:
        name = f"{exact[0]} {exact[1]}"
        if exact_found:
            return f"Encontré unidades exactas de {name}. No mezclé otros modelos: primero filtré condición y luego las ordené por ajuste, cuota, año y kilometraje."
        return f"No encontré un {name} exacto elegible. Las opciones que ves son alternativas, no sustitutos presentados como si fueran el mismo carro."
    if intent.get("farm") and intent.get("heavy_cargo"):
        return "Con grava, pasajeros y carga pesada, prioricé pickups capaces de cargar de verdad, buena altura y margen dentro de tu cuota. No hace falta pagar el máximo solo porque puedes."
    if intent.get("student") and intent.get("comfort"):
        return "Para universidad prioricé comodidad diaria, tamaño manejable en ciudad y una cuota con margen. Por eso un sedán bien resuelto puede ganarle a un city car más barato."
    if intent.get("student"):
        return "Para universidad prioricé facilidad de uso diario, costo razonable y tamaño práctico para ciudad."
    if filtered:
        return "Primero saqué del camino los anuncios con señales de riesgo y después ordené lo que quedó por ajuste real a tu uso y presupuesto."
    return "Ya tengo suficiente contexto. Ordené las opciones por ajuste a tu uso, presupuesto, año, kilometraje y calidad del anuncio."


def _rerank(body: Any, result: Any) -> Any:
    if not isinstance(result, dict) or result.get("phase") != "recommendation":
        return result

    pool = list(result.get("recommendations") or []) + list(result.get("explore") or [])
    if not pool:
        return result

    intent = _intent(body)
    enriched = _enrich(pool)
    pool = _dedupe(pool, enriched)

    risky = [c for c in pool if _hard_risk(c, enriched.get(str(c.get("url"))))]
    safe = [c for c in pool if c not in risky]
    if not safe:
        result["recommendations"] = []
        result["explore"] = []
        result["favorite"] = None
        result["reply"] = _reply(intent, [], len(risky), None, False)
        result["recommendation_brain"] = {"version": "v28", "quality_filtered": len(risky)}
        return result

    spec = _exact_spec(intent, safe)
    exact_found = False
    candidate_pool = safe
    if spec:
        exact = [c for c in safe if _is_exact(c, spec)]
        exact_found = bool(exact)
        result["exact_intent"] = {"make": spec[0], "model": spec[1], "found": exact_found, "count": len(exact)}
        if exact_found:
            candidate_pool = exact

    ranked = sorted(
        candidate_pool,
        key=lambda c: _mission_score(c, intent, enriched.get(str(c.get("url")))),
        reverse=True,
    )

    if intent.get("heavy_cargo") and (intent.get("farm") or intent.get("rough")) and not exact_found:
        pickups = [c for c in ranked if _norm(c.get("body_type")) == "pickup" or _WORK_PICKUP_MODELS.search(f"{_norm(c.get('make'))} {_norm(c.get('model'))}")]
        if len(pickups) >= 3:
            ranked = pickups + [c for c in ranked if c not in pickups]

    max_monthly = intent.get("monthly_max")
    if max_monthly:
        under = [c for c in ranked if _num(c.get("monthly_est")) is None or _num(c.get("monthly_est")) <= max_monthly]
        if len(under) >= 3:
            ranked = under + [c for c in ranked if c not in under]

    page = ranked[:12]
    top = page[:3]
    rest = page[3:]
    labels = ["Mi favorita para tu caso", "Mi segunda opción", "La alternativa que mantendría"]
    if intent.get("farm") and intent.get("heavy_cargo"):
        labels = ["Mejor para finca y carga", "Mejor equilibrio trabajo/cuota", "Alternativa robusta"]
    elif intent.get("student") and intent.get("comfort"):
        labels = ["Mejor equilibrio para universidad", "Más cómoda por tu dinero", "Alternativa práctica"]
    if exact_found and spec:
        labels = [f"Mejor {spec[0]} {spec[1]}", "Segunda unidad exacta", "Tercera unidad exacta"]

    for idx, card in enumerate(top):
        score = _mission_score(card, intent, enriched.get(str(card.get("url"))))
        card["advisor_score_v28"] = score
        card["best_for"] = labels[idx]
        card["strategy_label"] = labels[idx]
        card["match_pct"] = max(70, min(96, round(score)))
        if _suspicion_penalty(card, enriched.get(str(card.get("url")))) >= 25:
            card["caveat"] = "El anuncio tiene señales que ameritan validación adicional antes de reservar."

    result["recommendations"] = top
    result["explore"] = rest
    result["favorite"] = top[0] if top else None
    result["recommendation_count"] = len(top)
    result["explore_count"] = len(rest)
    result["loaded_options"] = page
    result["loaded_option_count"] = len(page)
    result["condition_filtered_count"] = len(risky)
    result["advisor_mode"] = "recommendation_brain_v28"
    result["reply"] = _reply(intent, top, len(risky), spec, exact_found)
    result["recommendation_brain"] = {
        "version": "v28",
        "intent": {k: v for k, v in intent.items() if k not in {"raw", "norm"} and v not in {None, False, ""}},
        "quality_filtered": len(risky),
        "candidate_count": len(candidate_pool),
        "exact": {"make": spec[0], "model": spec[1], "found": exact_found} if spec else None,
    }

    decision = result.get("decision")
    if isinstance(decision, dict):
        decision["recommendations"] = list(top)
        decision["explore"] = list(rest)
        decision["favorite"] = result["favorite"]
        decision["condition_filtered_count"] = len(risky)
    return result


def _patch_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None or getattr(prior, "_carly_v28_brain", False):
            continue

        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            try:
                commercial = v27.v26.v25.v20.commercial
                body = commercial._request_body(args, kwargs)
            except Exception:
                body = None
            result = __prior(*args, **kwargs)
            return _rerank(body, result)

        endpoint._carly_v28_brain = True
        route.endpoint = endpoint
        dependant.call = endpoint
        break


_patch_route()
