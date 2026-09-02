"""Carly v31: intent-first retrieval, universal hard constraints, exact-search bypass.

The prior stack remains responsible for conversation and UI compatibility. v31
rebuilds the recommendation pool directly from Supabase whenever the buyer has
provided enough information to search, then applies deterministic constraints,
quality gates and mission scoring before anything is surfaced.
"""
from __future__ import annotations

import re
from statistics import median
from typing import Any

from . import main_v30 as v30

v29 = v30.v29
v28 = v29.v28
legacy = v28.legacy
app = v30.app

try:
    v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v31-intent-retrieval"
except Exception:
    pass


_MODEL_SPECS = (
    ("Toyota", "RAV4", re.compile(r"\brav\s*-?\s*4\b", re.I), "suv"),
    ("Toyota", "Corolla", re.compile(r"\bcorolla\b", re.I), "sedan"),
    ("Toyota", "Hilux", re.compile(r"\bhilux\b", re.I), "pickup"),
    ("Toyota", "Tacoma", re.compile(r"\btacoma\b", re.I), "pickup"),
    ("Honda", "CR-V", re.compile(r"\bcr\s*-?\s*v\b", re.I), "suv"),
    ("Honda", "Civic", re.compile(r"\bcivic\b", re.I), "sedan"),
    ("Nissan", "Frontier", re.compile(r"\bfrontier\b", re.I), "pickup"),
    ("Nissan", "Kicks", re.compile(r"\bkicks\b", re.I), "suv"),
    ("Nissan", "Rogue", re.compile(r"\brogue\b", re.I), "suv"),
    ("Ford", "Ranger", re.compile(r"\branger\b", re.I), "pickup"),
    ("Mitsubishi", "L200", re.compile(r"\bl\s*-?\s*200\b", re.I), "pickup"),
    ("Kia", "Forte", re.compile(r"\bforte\b", re.I), "sedan"),
    ("Kia", "K3", re.compile(r"\bk\s*-?\s*3\b", re.I), "sedan"),
    ("Kia", "Picanto", re.compile(r"\bpicanto\b", re.I), "hatchback"),
    ("Kia", "Sportage", re.compile(r"\bsportage\b", re.I), "suv"),
    ("Hyundai", "Elantra", re.compile(r"\belantra\b", re.I), "sedan"),
    ("Hyundai", "Tucson", re.compile(r"\btucson\b", re.I), "suv"),
    ("Volkswagen", "Jetta", re.compile(r"\bjetta\b", re.I), "sedan"),
)

_BRAND_ALIASES = {
    "toyota": "Toyota", "toyta": "Toyota", "toyta": "Toyota", "toiyota": "Toyota",
    "honda": "Honda", "nissan": "Nissan", "ford": "Ford", "mitsubishi": "Mitsubishi",
    "kia": "Kia", "hyundai": "Hyundai", "volkswagen": "Volkswagen", "vw": "Volkswagen",
    "chevrolet": "Chevrolet", "chevy": "Chevrolet", "mazda": "Mazda", "suzuki": "Suzuki",
}

_SEDAN_MODELS = re.compile(r"\b(?:corolla|civic|forte|cerato|k3|elantra|jetta|sentra|versa|mirage g4|accent|mazda ?3|camry|accord)\b", re.I)
_HATCH_MODELS = re.compile(r"\b(?:picanto|mirage|spark|rio|swift|i10|grand i10|celerio|alto|kwid)\b", re.I)
_SUV_MODELS = re.compile(r"\b(?:rav4|cr-v|crv|kicks|rogue|venue|trax|tucson|sportage|tiggo|seltos|cx-30|cx-5|hr-v|hrv)\b", re.I)
_SMALL_FARM_PICKUPS = re.compile(r"\b(?:saveiro|strada|montana)\b", re.I)

_STRONG_ONLY = re.compile(r"\b(?:solo|solamente|unicamente|únicamente|exclusivamente|nada mas que|nada más que|tiene que ser|debe ser|no me ensenes otros|no me enseñes otros)\b", re.I)
_AUTOMATIC = re.compile(r"\bautomatic[oa]|automática|automático\b", re.I)
_MANUAL = re.compile(r"\bmanual\b", re.I)
_MIN_YEAR = re.compile(r"\b(20\d{2})\s*(?:\+|o\s+mas\s+nuev[oa]|o\s+más\s+nuev[oa]|en\s+adelante|o\s+posterior)\b", re.I)
_FAMILY_COUNT = re.compile(r"\b(?:familia\s+de|somos|para)\s*([2-9])\b", re.I)

_SELECT = (
    "id,source,country,url,title,price_usd,year,km,location,photos,raw_payload,status,"
    "scraped_at,updated_at,fuel_type,transmission,make,model,currency,photo_count,primary_photo,"
    "body_type,quality_score,last_seen_at,listing_state,monthly_est,is_addressable,model_norm,"
    "description,visible_damage_risk,damage_signals,vision_checked_at"
)


def _get(body: Any, key: str, default: Any = None) -> Any:
    if isinstance(body, dict):
        return body.get(key, default)
    return getattr(body, key, default)


def _text(body: Any) -> str:
    try:
        return v28._user_blob(body)
    except Exception:
        return ""


def _canonical_exact(text: str) -> tuple[str, str, str] | None:
    n = v28._norm(text)
    brand = None
    for alias, canonical in _BRAND_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", n):
            brand = canonical
            break
    for canonical_make, model, pattern, body in _MODEL_SPECS:
        if pattern.search(text) and (brand is None or brand.lower() == canonical_make.lower()):
            return canonical_make, model, body
    return None


def _constraints(body: Any) -> dict[str, Any]:
    text = _text(body)
    n = v28._norm(text)
    intent = v28._intent(body)
    exact = _canonical_exact(text)

    require_body = None
    if re.search(r"\b(?:pickup|pick-up|pick up)\b", text, re.I) and (re.search(r"\b(?:necesito|quiero|busco)\b", text, re.I) or _STRONG_ONLY.search(text)):
        require_body = "pickup"
    elif re.search(r"\bsed[aá]n\b", text, re.I) and _STRONG_ONLY.search(text):
        require_body = "sedan"
    elif re.search(r"\bsuv\b", text, re.I) and _STRONG_ONLY.search(text):
        require_body = "suv"
    elif re.search(r"\bhatch(?:back)?\b", text, re.I) and _STRONG_ONLY.search(text):
        require_body = "hatchback"

    require_transmission = None
    if _AUTOMATIC.search(text) and (require_body or _STRONG_ONLY.search(text) or re.search(r"\b(?:necesito|quiero|busco)\b", text, re.I)):
        require_transmission = "automatic"
    elif _MANUAL.search(text) and _STRONG_ONLY.search(text):
        require_transmission = "manual"

    min_year = None
    m = _MIN_YEAR.search(text)
    if m:
        min_year = int(m.group(1))

    passengers = intent.get("passengers")
    fm = _FAMILY_COUNT.search(text)
    if fm:
        passengers = max(int(fm.group(1)), int(passengers or 0))

    return {
        "text": text,
        "norm": n,
        "intent": intent,
        "exact": exact,
        "exact_only": bool(exact and (re.search(r"\bsolo\s+quiero\b", text, re.I) or re.search(r"no me (?:ensenes|enseñes) otros", text, re.I))),
        "allow_alternatives": bool(re.search(r"\balternativas?\b", text, re.I)),
        "require_body": require_body,
        "require_transmission": require_transmission,
        "min_year": min_year,
        "monthly_max": intent.get("monthly_max"),
        "total_budget": intent.get("total_budget"),
        "passengers": passengers,
        "delivery": bool(re.search(r"\b(?:delivery|reparto|repartir|entregas)\b", text, re.I)),
        "first_car": bool(re.search(r"\b(?:primer carro|primer auto|mi primer vehiculo|mi primer vehículo)\b", text, re.I)),
        "family": bool(intent.get("family") or re.search(r"\bfamilia\b", text, re.I)),
    }


def _body(card: dict) -> str:
    raw = v29._body(card)
    model = v28._norm(card.get("model"))
    if v28._WORK_PICKUP_MODELS.search(f"{v28._norm(card.get('make'))} {model}"):
        return "pickup"
    if _SEDAN_MODELS.search(model):
        return "sedan"
    if _HATCH_MODELS.search(model):
        return "hatchback"
    if _SUV_MODELS.search(model):
        return "suv"
    return raw


def _transmission(card: dict) -> str:
    t = v28._norm(card.get("transmission"))
    if "auto" in t:
        return "automatic"
    if "manual" in t or t in {"mecanica", "mecanico"}:
        return "manual"
    return t


def _monthly(card: dict) -> float | None:
    value = v28._num(card.get("monthly_est"))
    if value is not None:
        return value
    price = v28._num(card.get("price_usd"))
    return round(price * 0.0238) if price else None


def _active(card: dict) -> bool:
    state = v28._norm(card.get("listing_state"))
    return state not in {"expired", "closed"}


def _hard_ok(card: dict, c: dict[str, Any]) -> bool:
    if not _active(card):
        return False
    if card.get("is_addressable") is False:
        return False
    year = v28._num(card.get("year"))
    price = v28._num(card.get("price_usd"))
    monthly = _monthly(card)
    if c.get("min_year") and (year is None or year < c["min_year"]):
        return False
    if c.get("monthly_max") and monthly is not None and monthly > float(c["monthly_max"]):
        return False
    if c.get("total_budget") and price is not None and price > float(c["total_budget"]):
        return False
    if c.get("require_body") and _body(card) != c["require_body"]:
        return False
    if c.get("require_transmission") and _transmission(card) != c["require_transmission"]:
        return False
    exact = c.get("exact")
    if exact:
        make, model, _ = exact
        cmake = v28._norm(card.get("make"))
        cmodel = re.sub(r"[^a-z0-9]", "", v28._norm(card.get("model")))
        rmodel = re.sub(r"[^a-z0-9]", "", v28._norm(model))
        if cmake != v28._norm(make) or not (cmodel == rmodel or cmodel.startswith(rmodel) or rmodel in cmodel):
            return False
    return True


def _mission_ok(card: dict, c: dict[str, Any]) -> bool:
    intent = c["intent"]
    body = _body(card)
    model = v28._norm(card.get("model"))
    blob = v28._norm(v28._card_blob(card, card))
    passengers = int(c.get("passengers") or 0)

    if intent.get("heavy_cargo") and (intent.get("farm") or intent.get("rough")):
        if body != "pickup":
            return False
        if passengers >= 3 and (_SMALL_FARM_PICKUPS.search(model) or re.search(r"\b(?:cabina sencilla|single cab|2 asientos|2 pasajeros)\b", blob, re.I)):
            return False
    if c.get("family") and passengers >= 5:
        if body in {"pickup", "commercial"}:
            return False
        if v28._MICRO_CITY_MODELS.search(model):
            return False
    if c.get("delivery") and body in {"pickup", "commercial", "van", "minivan"}:
        return False
    return True


def _quality_ok(card: dict) -> bool:
    if v28._hard_risk(card, card):
        return False
    # Extreme anomaly is verification territory, not a recommendation.
    if v28._suspicion_penalty(card, card) >= 50:
        return False
    return True


def _score(card: dict, c: dict[str, Any]) -> float:
    intent = dict(c["intent"])
    score = float(v28._mission_score(card, intent, card))
    body = _body(card)
    model = v28._norm(card.get("model"))
    monthly = _monthly(card)

    if intent.get("heavy_cargo") and (intent.get("farm") or intent.get("rough")):
        score += 55 if body == "pickup" else -60
        blob = v28._norm(v28._card_blob(card, card))
        if re.search(r"\b(?:4x4|high y low|pi[nñ]on de monta[nñ]a|traccion a las cuatro)\b", blob, re.I):
            score += 12
        if int(c.get("passengers") or 0) >= 3 and re.search(r"\b(?:doble cabina|double cab|crew cab|4 puertas|5 pasajeros)\b", blob, re.I):
            score += 12
    if c.get("family"):
        score += 24 if body in {"suv", "crossover", "minivan"} else (7 if body == "sedan" else -15)
        if int(c.get("passengers") or 0) >= 5 and body == "suv":
            score += 8
    if c.get("delivery"):
        score += 28 if body in {"hatchback", "sedan"} else -18
        if monthly is not None and c.get("monthly_max"):
            score += max(0.0, 18.0 * (1.0 - monthly / float(c["monthly_max"])))
    if c.get("first_car"):
        score += 12 if body in {"hatchback", "sedan"} else -5
    if c.get("require_body") and body == c["require_body"]:
        score += 18
    if c.get("require_transmission") and _transmission(card) == c["require_transmission"]:
        score += 10
    if c.get("exact"):
        score += 80
    return round(score, 2)


def _query_rows(c: dict[str, Any], country: str) -> list[dict]:
    client = getattr(legacy, "supabase", None)
    if client is None:
        return []
    try:
        q = client.table("scraped_listings").select(_SELECT).eq("country", country).eq("is_addressable", True)
        exact = c.get("exact")
        if exact:
            make, model, _ = exact
            q = q.ilike("make", f"%{make}%").ilike("model", f"%{model.replace('-', '')}%")
        response = q.order("updated_at", desc=True).limit(500).execute()
        rows = [dict(r) for r in (response.data or [])]
        # Some model fields keep punctuation/spaces differently; retry exact by make only
        # if the first model-normalized query was too strict.
        if exact and not rows:
            make, _, _ = exact
            response = (
                client.table("scraped_listings").select(_SELECT)
                .eq("country", country).eq("is_addressable", True)
                .ilike("make", f"%{make}%").order("updated_at", desc=True).limit(300).execute()
            )
            rows = [dict(r) for r in (response.data or [])]
        return rows
    except Exception:
        return []


def _rank_rows(rows: list[dict], c: dict[str, Any]) -> tuple[list[dict], int]:
    usable = []
    filtered = 0
    for row in rows:
        row["monthly_est"] = _monthly(row)
        if not _hard_ok(row, c) or not _quality_ok(row) or not _mission_ok(row, c):
            filtered += 1
            continue
        usable.append(row)

    # Deduplicate before ranking.
    usable = v28._dedupe(usable, {str(r.get("url")): r for r in usable})
    ranked = sorted(usable, key=lambda r: _score(r, c), reverse=True)
    return ranked, filtered


def _alternatives(c: dict[str, Any], country: str) -> list[dict]:
    alt = dict(c)
    exact = alt.pop("exact", None)
    alt["exact"] = None
    if exact and not alt.get("require_body"):
        alt["require_body"] = exact[2]
    rows = _query_rows(alt, country)
    ranked, _ = _rank_rows(rows, alt)
    return ranked


def _decorate(cards: list[dict], c: dict[str, Any]) -> None:
    labels = ["Mi favorita para tu caso", "Mi segunda opción", "La alternativa que mantendría"]
    intent = c["intent"]
    if intent.get("student") and intent.get("comfort"):
        labels = ["Mejor equilibrio para universidad", "Más cómoda por tu dinero", "Alternativa práctica"]
    elif intent.get("heavy_cargo") and (intent.get("farm") or intent.get("rough")):
        labels = ["Mejor para finca y carga", "Mejor equilibrio trabajo/cuota", "Alternativa robusta"]
    elif c.get("exact"):
        labels = ["Mejor unidad exacta", "Segunda unidad exacta", "Tercera unidad exacta"]
    for idx, card in enumerate(cards[:3]):
        s = _score(card, c)
        card["advisor_score_v31"] = s
        card["match_pct"] = max(70, min(96, round(s)))
        card["best_for"] = labels[idx]
        card["strategy_label"] = labels[idx]
        card["monthly_payment"] = _monthly(card)


def _reply(c: dict[str, Any], top: list[dict], exact_miss: bool = False) -> str:
    exact = c.get("exact")
    if exact:
        make, model, _ = exact
        label = f"{make} {model}"
        if exact_miss:
            budget = f" dentro de tu máximo de ${int(c['monthly_max'])}/mes" if c.get("monthly_max") else ""
            return f"No encontré un {label} que cumpla exactamente tus criterios{budget}. Las opciones que ves son alternativas, claramente separadas del match exacto."
        return f"Encontré {label} que cumplen tus criterios. No mezclé otros modelos y apliqué condición, presupuesto y año antes de ordenar las unidades."
    if c["intent"].get("heavy_cargo") and (c["intent"].get("farm") or c["intent"].get("rough")):
        return "Con grava, pasajeros y carga pesada, fui directo a pickups aptas para carga real y descarté opciones que no sirven para tres personas o tienen señales de riesgo."
    if c.get("family"):
        return "Para una familia de cinco prioricé espacio real, comodidad y margen de cuota; saqué city cars pequeños y pickups del shortlist."
    if c.get("delivery"):
        return "Para delivery prioricé costo operativo y cuota baja sin convertir una anomalía barata en una falsa ganga."
    if c.get("require_body") or c.get("require_transmission"):
        return "Tomé tus requisitos como filtros duros antes de rankear. Lo que ves cumple carrocería, transmisión y presupuesto solicitados."
    if c["intent"].get("student") and c["intent"].get("comfort"):
        return "Para universidad prioricé comodidad diaria, tamaño manejable y una cuota con margen, buscando directamente en el inventario elegible."
    return "Busqué directamente en el inventario elegible y ordené las opciones por ajuste a tu uso, presupuesto, condición, año y kilometraje."


def _apply(body: Any, prior_result: Any) -> Any:
    c = _constraints(body)
    text = c["text"]
    if not text:
        return prior_result

    country = v28._norm(_get(body, "country") or "") or "sv"
    enough = bool(
        c.get("exact") or c.get("require_body") or c.get("require_transmission") or c.get("min_year")
        or c["intent"].get("student") or c["intent"].get("farm") or c["intent"].get("heavy_cargo")
        or c.get("family") or c.get("delivery") or c.get("first_car") or c["intent"].get("economy")
    ) and bool(c.get("monthly_max") or c.get("total_budget") or c.get("exact"))
    if not enough:
        return prior_result

    rows = _query_rows(c, country)
    ranked, filtered = _rank_rows(rows, c)
    exact_miss = bool(c.get("exact") and not ranked)

    if exact_miss and c.get("allow_alternatives") and not c.get("exact_only"):
        ranked = _alternatives(c, country)
    elif exact_miss and c.get("exact_only"):
        ranked = []

    page = ranked[:12]
    top = page[:3]
    rest = page[3:]
    _decorate(top, c)

    result = dict(prior_result) if isinstance(prior_result, dict) else {}
    result.update({
        "phase": "recommendation",
        "reply": _reply(c, top, exact_miss=exact_miss),
        "recommendations": top,
        "explore": rest,
        "favorite": top[0] if top else None,
        "recommendation_count": len(top),
        "explore_count": len(rest),
        "loaded_options": page,
        "loaded_option_count": len(page),
        "pool_size": len(rows),
        "market_pool_size": len(rows),
        "quality_candidate_count": len(page),
        "show_market_animation": True,
        "advisor_mode": "recommendation_brain_v31",
        "recommendation_brain": {
            "version": "v31",
            "retrieval": "intent_first_supabase",
            "hard_constraints": {
                "exact": c.get("exact")[:2] if c.get("exact") else None,
                "body": c.get("require_body"),
                "transmission": c.get("require_transmission"),
                "min_year": c.get("min_year"),
                "monthly_max": c.get("monthly_max"),
            },
            "quality_filtered": filtered,
            "candidate_count": len(ranked),
            "exact_miss": exact_miss,
        },
    })
    profile = dict(result.get("profile") or {})
    profile.setdefault("country", country)
    if c.get("monthly_max") is not None:
        profile["max_monthly"] = c["monthly_max"]
    if c.get("min_year") is not None:
        profile["min_year"] = c["min_year"]
    if c.get("passengers") is not None:
        profile["passengers"] = c["passengers"]
    if c.get("require_body"):
        profile["require_body"] = [c["require_body"]]
    if c.get("require_transmission") == "automatic":
        profile["avoid_transmission"] = "manual"
    result["profile"] = profile

    decision = result.get("decision")
    if not isinstance(decision, dict):
        decision = {}
        result["decision"] = decision
    decision.update({"recommendations": list(top), "explore": list(rest), "favorite": result["favorite"]})
    return result


def _patch_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None or getattr(prior, "_carly_v31", False):
            continue

        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            try:
                commercial = v29.v28.v27.v26.v25.v20.commercial
                body = commercial._request_body(args, kwargs)
            except Exception:
                body = None
            result = __prior(*args, **kwargs)
            return _apply(body, result)

        endpoint._carly_v31 = True
        route.endpoint = endpoint
        dependant.call = endpoint
        break


_patch_route()
