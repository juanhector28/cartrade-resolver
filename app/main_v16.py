"""Carly v16: deterministic preference mutation and truthful availability.

Common post-shortlist instructions mutate structured buyer state instead of being
sent to the LLM. Body-type changes, monthly-budget updates, explicit rejection of
visible units, and "more options" requests trigger a fresh inventory query and
rerank at zero model calls.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any

from . import main_v15 as v15
from .carly_advisor import advisor_score, advisor_snapshot

app = v15.app
commercial = v15.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v16-dynamic-preference-state"

_PAGE_SIZE = 6
_BODY_PATTERNS = {
    "sedan": re.compile(r"\bsed[aá]n(?:es)?\b", re.I),
    "hatchback": re.compile(r"\bhatch(?:back)?s?\b", re.I),
    "suv": re.compile(r"\bsuvs?\b", re.I),
    "pickup": re.compile(r"\bpick[ -]?ups?\b", re.I),
}
_HARD_BODY_RE = re.compile(r"\b(?:quiero|busco|necesito|solo|solamente|dame|muestrame|muéstrame)\b", re.I)
_SOFT_BODY_RE = re.compile(r"\b(?:quizas|quizás|podemos|veamos|consideremos|tambien|también|abierto a)\b", re.I)
_MORE_RE = re.compile(r"\b(?:mas|más|otras?|siguientes)\s+(?:opciones?|carros?|vehiculos?)\b|\b(?:ver|mostrar|muestrame|muéstrame|dame)\s+(?:mas|más)\b", re.I)
_MONTHLY_RE = re.compile(
    r"(?:hasta|tope|techo|puedo pagar|me puedo ir hasta|por)\s*\$?\s*(\d{2,4})\s*(?:dolares|dólares|usd)?(?:\s*(?:al mes|mensual|por mes|/mes))?",
    re.I,
)
_MARGIN_RE = re.compile(r"\b(?:margen|puedo pagar|me queda comodo|me queda cómodo|techo|tope|hasta)\b", re.I)
_REJECT_RE = re.compile(r"\b(?:no quiero|descarta|descartar|quita|quitar|fuera|no me interesa|esta chocado|está chocado|chocado|dañado|danado)\b", re.I)
_BRANDS = ("Toyota", "Honda", "Nissan", "Kia", "Hyundai", "Mazda", "Suzuki", "Mitsubishi", "Ford", "Chevrolet", "Volkswagen", "Subaru", "Jeep", "BMW", "Mercedes-Benz", "Audi")


def _norm(value: Any) -> str:
    s = unicodedata.normalize("NFKD", str(value or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip()


def _messages(body) -> list[Any]:
    return list(getattr(body, "messages", None) or []) if body is not None else []


def _user_turns(body) -> list[str]:
    out = []
    for m in _messages(body):
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        if str(role or "").lower() != "user":
            continue
        text = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        out.append(str(text or ""))
    return out


def _clone_profile(profile: Any) -> Any:
    try:
        return copy.deepcopy(profile)
    except Exception:
        return profile


def _set(profile: Any, field: str, value: Any) -> None:
    try:
        setattr(profile, field, value)
    except Exception:
        pass


def _body_mutation(latest: str) -> tuple[str | None, bool]:
    body = next((name for name, pattern in _BODY_PATTERNS.items() if pattern.search(latest)), None)
    if not body:
        return None, False
    hard = bool(_HARD_BODY_RE.search(latest)) and not bool(_SOFT_BODY_RE.search(latest))
    # "quiero sedanes, más opciones" is unequivocally a hard search mutation.
    if re.search(r"\bquiero\b", latest, re.I):
        hard = True
    return body, hard


def _monthly_mutation(latest: str) -> float | None:
    n = _norm(latest)
    match = _MONTHLY_RE.search(latest)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except Exception:
        return None
    if not (25 <= value <= 2000):
        return None
    # Bare "por $500" only becomes a budget mutation when the language signals
    # affordability/margin; this avoids treating vehicle prices as monthly budget.
    if "por" in n and not _MARGIN_RE.search(latest) and not re.search(r"(?:al mes|mensual|/mes)", latest, re.I):
        return None
    return value


def _key(car: dict):
    return v15._key(car)


def _find_rejected_keys(body, shown: list[dict]) -> set[Any]:
    """Persist visible-unit rejection by replaying explicit user rejection turns."""
    rejected: set[Any] = set()
    for text in _user_turns(body):
        if not _REJECT_RE.search(text):
            continue
        n = _norm(text)
        matched = []
        for car in shown:
            make = _norm(car.get("make")); model = _norm(car.get("model")); year = str(car.get("year") or "")
            if model and model in n:
                matched.append(car); continue
            if make and make in n:
                candidates = [c for c in shown if _norm(c.get("make")) == make]
                if len(candidates) == 1 or year in n or re.search(r"\bese\b|\besa\b", n):
                    matched.extend(candidates)
        # "ese" with no model can safely refer to the only visible card if there is one.
        if not matched and re.search(r"\bese\b|\besa\b", n) and len(shown) == 1:
            matched = shown
        rejected.update(_key(c) for c in matched)
    return rejected


def _explicit_avoid_brands(body) -> set[str]:
    avoids: set[str] = set()
    for text in _user_turns(body):
        n = _norm(text)
        if not _REJECT_RE.search(text):
            continue
        for brand in _BRANDS:
            b = _norm(brand)
            if re.search(rf"\b(?:no quiero|sin|evita|evitar)\s+(?:un\s+|una\s+)?{re.escape(b)}s?\b", n) and not re.search(r"\bese\b|\besa\b", n):
                avoids.add(brand)
    return avoids


def _mutated_profile(body, shown: list[dict]):
    base = v15._profile(body, shown)
    if base is None:
        return None, {}
    profile = _clone_profile(base)
    latest = v15._latest(body)
    changes: dict[str, Any] = {}

    # Replay body instructions so state survives later turns such as rejection.
    body_choice = None; hard_choice = False
    for text in _user_turns(body):
        choice, hard = _body_mutation(text)
        if choice:
            body_choice, hard_choice = choice, hard
    if body_choice:
        if hard_choice:
            _set(profile, "require_body", [body_choice])
            _set(profile, "prefer_body", [body_choice])
        else:
            _set(profile, "prefer_body", [body_choice])
            _set(profile, "require_body", [])
        changes["body_type"] = body_choice
        changes["body_hard"] = hard_choice

    monthly = None
    for text in _user_turns(body):
        parsed = _monthly_mutation(text)
        if parsed is not None:
            monthly = parsed
    if monthly is not None:
        _set(profile, "max_monthly", monthly)
        changes["max_monthly"] = monthly

    avoids = _explicit_avoid_brands(body)
    if avoids:
        existing = list(getattr(profile, "avoid_brands", None) or [])
        merged = list(dict.fromkeys(existing + sorted(avoids)))
        _set(profile, "avoid_brands", merged)
        changes["avoid_brands"] = merged
    return profile, changes


def _card(entry: dict, profile: Any, rank: int) -> dict:
    try:
        card = commercial.legacy._carly_card(entry)
    except Exception:
        card = dict(entry)
    snap = advisor_snapshot(entry, profile, rank)
    card["advisor_score"] = snap["score"]
    card["advisor_snapshot"] = snap
    card["best_for"] = snap["label"]
    card["strategy_label"] = snap["label"]
    card["advisor_reason"] = "; ".join((snap.get("reasons") or [])[:2])
    return card


def _is_search_mutation(body) -> bool:
    latest = v15._latest(body)
    body_choice, _ = _body_mutation(latest)
    return bool(body_choice or _monthly_mutation(latest) is not None or _MORE_RE.search(latest) or _REJECT_RE.search(latest))


def _dynamic_search(body) -> dict | None:
    if body is None or not _is_search_mutation(body):
        return None
    shown = v15.v14._unique(list(getattr(body, "shown_cars", None) or []))
    if not shown:
        return None
    profile, changes = _mutated_profile(body, shown)
    if profile is None:
        return None
    latest = v15._latest(body)
    body_choice, hard_body = _body_mutation(latest)
    rejected = _find_rejected_keys(body, shown)
    country = getattr(body, "country", None)
    try:
        pool = v15.v14._unique(list(commercial.legacy._carly_inventory(profile, country=country) or []))
    except Exception:
        return None

    avoid_brands = {_norm(x) for x in (getattr(profile, "avoid_brands", None) or [])}
    eligible = [c for c in pool if _key(c) not in rejected and _norm(c.get("make")) not in avoid_brands]

    # A direct body request controls the result set now. A soft "sedanes también"
    # prioritizes sedans first but keeps the broader search available.
    active_body = changes.get("body_type")
    hard_active = bool(changes.get("body_hard"))
    if active_body and hard_active:
        eligible = [c for c in eligible if _norm(c.get("body_type")) == active_body]

    seen = {_key(c) for c in shown}
    wants_more = bool(_MORE_RE.search(latest))
    if wants_more:
        eligible = [c for c in eligible if _key(c) not in seen]

    def score(car: dict) -> float:
        s = advisor_score(car, profile)
        if active_body and _norm(car.get("body_type")) == active_body:
            s += 25.0
        return s

    ranked = sorted(eligible, key=score, reverse=True)
    page = ranked[:_PAGE_SIZE]
    cards = [_card(row, profile, i + 1) for i, row in enumerate(page)]
    left = max(0, len(ranked) - len(page))

    if active_body:
        label = {"sedan":"sedanes", "hatchback":"hatchbacks", "suv":"SUVs", "pickup":"pickups"}.get(active_body, active_body)
        lead = f"Actualicé tu búsqueda a {label}"
    elif "max_monthly" in changes:
        lead = f"Actualicé tu techo a ~${changes['max_monthly']:,.0f}/mes"
    elif rejected:
        lead = "Descarté la unidad que señalaste"
    else:
        lead = "Actualicé la búsqueda"
    if rejected and active_body:
        lead += " y dejé fuera la unidad que descartaste"
    reply = lead + f". Encontré {len(cards)} opciones para mostrarte ahora."
    if left:
        reply += f" Quedan {left} opciones elegibles después de estas."
    elif cards:
        reply += " Estas son las últimas que pasan el filtro actual."
    else:
        reply = lead + ". No encontré unidades confirmadas que pasen ese filtro ahora; puedo relajar un criterio sin tocar los que marcaste como obligatorios."

    return {
        "phase": "recommendation" if cards else "conversation",
        "reply": reply,
        "recommendations": cards,
        "explore": [],
        "favorite": cards[0] if cards else None,
        "recommendation_count": len(cards),
        "explore_count": 0,
        "market_pool_size": len(pool),
        "pool_size": len(pool),
        "eligible_option_count": len(ranked),
        "quality_candidate_count": len(ranked),
        "loaded_option_count": len(cards),
        "more_options_available": left > 0,
        "more_options_count": left,
        "option_count_semantics": "market_pool_vs_current_eligible",
        "replace_recommendations": True,
        "append_recommendations": False,
        "clear_recommendations": False,
        "profile_mutations": changes,
        "excluded_visible_count": len(rejected),
        "token_path": "deterministic_dynamic_preference",
        "advisor_mode": "dynamic_preference_state_v16",
        "llm_calls": 0,
    }


def _truthful_counts(result: Any) -> Any:
    """Give the UI explicit market/eligible/loaded semantics from first render."""
    if not isinstance(result, dict) or result.get("phase") != "recommendation":
        return result
    market = int(result.get("market_pool_size") or result.get("pool_size") or 0)
    strong = list(result.get("recommendations") or [])
    explore = list(result.get("explore") or [])
    eligible = int(result.get("eligible_option_count") or result.get("quality_candidate_count") or (len(strong) + len(explore)))
    loaded = len(strong) + len(explore)
    result["market_pool_size"] = market
    result["eligible_option_count"] = eligible
    result["loaded_option_count"] = loaded
    result["option_count_semantics"] = "market_pool_vs_current_eligible"
    # Never advertise a continuation merely because the raw market pool is large.
    remaining = max(0, eligible - loaded)
    result["more_options_available"] = remaining > 0
    result["more_options_count"] = remaining
    return result


def _patch() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None); dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None:
            continue
        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = commercial._request_body(args, kwargs)
            direct = _dynamic_search(body)
            if direct is not None:
                return direct
            return _truthful_counts(__prior(*args, **kwargs))
        route.endpoint = endpoint; dependant.call = endpoint; break

_patch()
