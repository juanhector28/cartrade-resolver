"""Carly v39: constraint semantics + focused retrieval.

Production audits exposed three related failures:
- a valid `no pickup / no Kia / no Nissan` profile could still surface legacy pickups
  when v31's original `enough` heuristic did not trigger intent-first retrieval;
- strong exact intent (`Honda CRV`) and explicitly limited fallback brands were not
  reliably preserved;
- soft model preference (`Corolla, Civic o equivalente`) could be misread as exact.

v39 makes the final shortlist authoritative: whenever the buyer supplied a budget
plus meaningful constraints/preferences, it performs a focused Supabase retrieval,
applies the current hard/quality/vision gates, then rebuilds the surfaced shortlist.
It also pushes year/price/transmission/allowed-make filters into retrieval so rare
6/7-seat candidates are not starved by an arbitrary latest-500 window.
"""
from __future__ import annotations

import re
from typing import Any

from . import main_v38 as v38

app = v38.app
v37 = v38.v37
v36 = v37.v36
v31 = v38.v31
v28 = v38.v28
legacy = v38.legacy

_ORIG_APPLY = v38._apply
_ORIG_CONSTRAINTS = v37._constraints
_ORIG_QUERY_ROWS = v31._query_rows
_ORIG_HARD_OK = v31._hard_ok
_ORIG_MISSION_OK = v31._mission_ok
_ORIG_SCORE = v31._score

try:
    v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v39-constraint-semantics"
except Exception:
    pass

# Extend canonical brands used only by this parser. Existing behavior is preserved.
v31._BRAND_ALIASES.setdefault("subaru", "Subaru")

_AUTO = re.compile(r"\b(?:automatic[oa]|autom[aá]tic[oa])\b", re.I)
_MANUAL = re.compile(r"\bmanual\b", re.I)
_SOFT_TRANSMISSION = re.compile(r"\b(?:preferir[ií]a|prefiero|idealmente|si\s+se\s+puede)\b", re.I)
_EQUIVALENT = re.compile(r"\bo\s+(?:algo\s+)?equivalente\b", re.I)
_NO_SMALL = re.compile(r"\b(?:no\s+quiero|sin)\s+(?:un\s+)?(?:carro\s+)?(?:demasiado\s+)?peque[nñ]o\b|\bno\s+quiero\s+microcarros?\b", re.I)
_LUGGAGE = re.compile(r"\b(?:bastante|mucho)\s+equipaje\b|\b(?:maletas|equipaje|coche\s+de\s+beb[eé])\b", re.I)
_ALT_BRANDS = re.compile(r"\balternativas?(?:\s+\w+){0,4}\s+de\s+([^.;]+)", re.I)
_MAX_ALTS = re.compile(r"\bm[aá]ximo\s+([1-9])\s+alternativas?\b", re.I)
_NADA_DE = re.compile(r"\bnada\s+de\s+([a-zA-ZÁÉÍÓÚÜÑáéíóúüñ-]+)\b", re.I)
_STRONG_ACTION = re.compile(r"\b(?:estoy\s+buscando|ando\s+buscando|busco|quiero|necesito)\b", re.I)

_EXTRA_MODELS = [
    ("Honda", "HR-V", re.compile(r"\bhr\s*[- ]?\s*v\b", re.I), "suv"),
]


def _all_model_specs():
    return list(v31._MODEL_SPECS) + _EXTRA_MODELS


def _model_mentions(text: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for make, model, pattern, body in _all_model_specs():
        if pattern.search(text or ""):
            item = (make, model, body)
            if item not in found:
                found.append(item)
    return found


def _pattern_for(exact: tuple[str, str, str] | None):
    if not exact:
        return None
    make, model, _ = exact
    for cmake, cmodel, pattern, _body in _all_model_specs():
        if cmake == make and cmodel == model:
            return pattern
    return None


def _strong_exact(text: str, candidate: tuple[str, str, str] | None):
    """Require a nearby search/want verb before turning a model mention into exact intent."""
    pattern = _pattern_for(candidate)
    if not candidate or pattern is None:
        return None
    for match in pattern.finditer(text or ""):
        prefix = (text or "")[max(0, match.start() - 75):match.start()]
        # Model should be close to the action phrase. This rejects e.g.
        # `Prefiero gastar un poco más por un Corolla, Civic o equivalente`.
        action = list(_STRONG_ACTION.finditer(prefix))
        if action and len(prefix) - action[-1].end() <= 42:
            tail = prefix[action[-1].end():]
            if not re.search(r"\bprefier[oa]|preferir[ií]a\b", tail, re.I):
                return candidate
    return None


def _brand_from_token(token: str) -> str | None:
    n = v28._norm(token)
    return v31._BRAND_ALIASES.get(n)


def _fallback_brands(text: str) -> list[str]:
    m = _ALT_BRANDS.search(text or "")
    if not m:
        return []
    clause = v28._norm(m.group(1))
    out: list[str] = []
    for alias, canonical in v31._BRAND_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", clause) and canonical not in out:
            out.append(canonical)
    return out


def _preferred_models(text: str) -> list[tuple[str, str]]:
    mentions = _model_mentions(text)
    if len(mentions) >= 2 and (_EQUIVALENT.search(text or "") or re.search(r"\bprefier", text or "", re.I)):
        return [(make, model) for make, model, _ in mentions]
    return []


def _hard_transmission(text: str, current: str | None) -> str | None:
    # Preserve an already-hard parse. Otherwise make an explicit standalone
    # transmission hard unless the local wording clearly marks it as optional.
    if current:
        return current
    for regex, value in ((_AUTO, "automatic"), (_MANUAL, "manual")):
        for match in regex.finditer(text or ""):
            window = (text or "")[max(0, match.start() - 35):min(len(text or ""), match.end() + 28)]
            if not _SOFT_TRANSMISSION.search(window):
                return value
    return None


def _constraints(body: Any) -> dict[str, Any]:
    c = dict(_ORIG_CONSTRAINTS(body))
    text = str(c.get("text") or "")

    candidate = v31._canonical_exact(text)
    strong = _strong_exact(text, candidate)
    mentions = _model_mentions(text)
    preferred = _preferred_models(text)

    if strong:
        c["exact"] = strong
    elif c.get("exact") and (preferred or len(mentions) >= 2 or _EQUIVALENT.search(text)):
        c["exact"] = None
    c["preferred_models"] = preferred

    c["require_transmission"] = _hard_transmission(text, c.get("require_transmission"))
    c["avoid_small"] = bool(_NO_SMALL.search(text))
    c["luggage"] = bool(_LUGGAGE.search(text))

    avoid = list(c.get("avoid_brands") or [])
    for m in _NADA_DE.finditer(text):
        brand = _brand_from_token(m.group(1))
        if brand and brand not in avoid:
            avoid.append(brand)
    c["avoid_brands"] = avoid

    c["fallback_brands"] = _fallback_brands(text)
    m = _MAX_ALTS.search(text)
    c["max_alternatives"] = int(m.group(1)) if m else None
    return c


def _hard_ok(card: dict, c: dict[str, Any]) -> bool:
    if not _ORIG_HARD_OK(card, c):
        return False
    allowed = {v28._norm(x) for x in (c.get("allowed_brands") or [])}
    if allowed and v28._norm(card.get("make")) not in allowed:
        return False
    return True


def _mission_ok(card: dict, c: dict[str, Any]) -> bool:
    if not _ORIG_MISSION_OK(card, c):
        return False
    if c.get("avoid_small") and v28._MICRO_CITY_MODELS.search(v28._norm(card.get("model"))):
        return False
    return True


def _score(card: dict, c: dict[str, Any]) -> float:
    score = float(_ORIG_SCORE(card, c))
    make = v28._norm(card.get("make"))
    model = re.sub(r"[^a-z0-9]", "", v28._norm(card.get("model")))
    body = v31._body(card)

    preferred_brands = {v28._norm(x) for x in (c.get("prefer_brands") or [])}
    if make and make in preferred_brands:
        score += 10

    for pmake, pmodel in (c.get("preferred_models") or []):
        pnorm = re.sub(r"[^a-z0-9]", "", v28._norm(pmodel))
        if make == v28._norm(pmake) and (model == pnorm or model.startswith(pnorm) or pnorm in model):
            score += 20
            break

    if c.get("luggage") and int(c.get("passengers") or 0) >= 4:
        if body in {"suv", "crossover", "minivan"}:
            score += 18
        elif body == "sedan":
            score += 6
        elif body == "hatchback":
            score -= 12
    return round(score, 2)


def _query_rows(c: dict[str, Any], country: str) -> list[dict]:
    """Push high-confidence scalar constraints into Supabase before the bounded read."""
    client = getattr(legacy, "supabase", None)
    if client is None:
        return []
    try:
        q = (
            client.table("scraped_listings").select(v31._SELECT)
            .eq("country", country).eq("is_addressable", True).eq("listing_state", "indexed")
        )
        exact = c.get("exact")
        if exact:
            # Make-only server filter avoids CR-V/CRV punctuation mismatches; exact
            # model identity remains a hard client-side gate.
            q = q.ilike("make", f"%{exact[0]}%")
        if c.get("min_year"):
            q = q.gte("year", int(c["min_year"]))
        if c.get("require_transmission") == "automatic":
            q = q.ilike("transmission", "%Auto%")
        elif c.get("require_transmission") == "manual":
            q = q.ilike("transmission", "%Manual%")

        price_cap = None
        if c.get("total_budget"):
            price_cap = float(c["total_budget"])
        if c.get("monthly_max"):
            implied = float(c["monthly_max"]) / 0.0238 * 1.03
            price_cap = min(price_cap, implied) if price_cap else implied
        if price_cap:
            q = q.lte("price_usd", round(price_cap, 2))

        allowed = list(c.get("allowed_brands") or [])
        if allowed:
            q = q.in_("make", allowed)

        response = q.order("updated_at", desc=True).limit(900).execute()
        return [dict(r) for r in (response.data or [])]
    except Exception:
        # Correctness beats optimization if a provider/operator shape changes.
        return _ORIG_QUERY_ROWS(c, country)


def _alternatives(c: dict[str, Any], country: str) -> list[dict]:
    alt = dict(c)
    exact = alt.get("exact")
    alt["exact"] = None
    if exact and not alt.get("require_body"):
        alt["require_body"] = exact[2]
    if c.get("fallback_brands"):
        alt["allowed_brands"] = list(c["fallback_brands"])
    rows = _query_rows(alt, country)
    ranked, _ = v31._rank_rows(rows, alt)
    maximum = int(c.get("max_alternatives") or 0)
    return ranked[:maximum] if maximum else ranked


def _should_retrieve(c: dict[str, Any]) -> bool:
    if c.get("exact"):
        return True
    budget = c.get("monthly_max") or c.get("total_budget")
    if not budget:
        return False
    focus = bool(
        c.get("require_body") or c.get("require_transmission") or c.get("min_year")
        or c.get("avoid_body") or c.get("avoid_brands") or c.get("prefer_brands")
        or c.get("preferred_models") or c.get("passengers") or c.get("avoid_small")
        or c.get("luggage") or c.get("family") or c.get("delivery") or c.get("first_car")
        or (c.get("intent") or {}).get("comfort") or (c.get("intent") or {}).get("economy")
        or (c.get("intent") or {}).get("farm") or (c.get("intent") or {}).get("rough")
    )
    return focus


def _rebuild(body: Any, prior_result: dict, c: dict[str, Any]) -> dict:
    country = v28._norm(v31._get(body, "country") or "") or "sv"
    rows = _query_rows(c, country)
    ranked, filtered = v31._rank_rows(rows, c)
    exact_miss = bool(c.get("exact") and not ranked)

    if exact_miss and c.get("allow_alternatives") and not c.get("exact_only"):
        ranked = _alternatives(c, country)
    elif exact_miss and c.get("exact_only"):
        ranked = []

    limit = int(c.get("max_alternatives") or 12) if exact_miss else 12
    page = ranked[:limit]
    top = page[:3]
    rest = page[3:]

    display_c = dict(c)
    if exact_miss:
        display_c["exact"] = None
    v31._decorate(top, display_c)

    result = dict(prior_result or {})
    result.update({
        "phase": "recommendation" if top else "conversation",
        "reply": v31._reply(c, top, exact_miss=exact_miss),
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
        "advisor_mode": "recommendation_brain_v39",
        "recommendation_brain": {
            "version": "v39",
            "retrieval": "focused_intent_supabase",
            "hard_constraints": {
                "exact": c.get("exact")[:2] if c.get("exact") else None,
                "body": c.get("require_body"),
                "avoid_body": c.get("avoid_body") or [],
                "transmission": c.get("require_transmission"),
                "min_year": c.get("min_year"),
                "monthly_max": c.get("monthly_max"),
                "total_budget": c.get("total_budget"),
                "avoid_brands": c.get("avoid_brands") or [],
                "passengers": c.get("passengers"),
            },
            "preferred_models": c.get("preferred_models") or [],
            "fallback_brands": c.get("fallback_brands") or [],
            "max_alternatives": c.get("max_alternatives"),
            "quality_filtered": filtered,
            "candidate_count": len(ranked),
            "exact_miss": exact_miss,
            "final_hard_filter_authoritative": True,
            "focused_scalar_query": True,
            "vision_transport": "server_download_avif_to_jpeg_base64",
        },
    })
    v38._refresh_profile(result, c)

    if not top:
        result.pop("decision", None)
        result["decision_room"] = False
    else:
        result.pop("decision", None)
        result["decision"] = v37.carly_decision_room.build_decision(result, country=country)
        result["decision_room"] = True
    return result


def _apply(body: Any, prior_result: Any) -> Any:
    result = _ORIG_APPLY(body, prior_result)
    if not isinstance(result, dict):
        return result
    c = _constraints(body)
    if _should_retrieve(c):
        result = _rebuild(body, result, c)
    else:
        brain = dict(result.get("recommendation_brain") or {})
        if brain:
            brain["version"] = "v39"
            brain["final_hard_filter_authoritative"] = True
            result["recommendation_brain"] = brain
            result["advisor_mode"] = "recommendation_brain_v39"
    return result


# Patch globals resolved dynamically by the v31-installed route and ranker.
v31._constraints = _constraints
v37._constraints = _constraints
v31._hard_ok = _hard_ok
v31._mission_ok = _mission_ok
v31._score = _score
v31._query_rows = _query_rows
v31._alternatives = _alternatives
v31._apply = _apply
