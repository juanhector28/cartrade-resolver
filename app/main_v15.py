"""Carly v15: zero-token continuation over the real filtered market pool.

Explicit requests such as "ver 6 más" or "muéstrame las siguientes 6" are
resolved deterministically. Carly reuses the buyer profile, queries the same
quality-filtered inventory, excludes already shown units, ranks the remainder,
and returns the next page without any LLM call.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import main_v14 as v14
from .carly_advisor import advisor_score, advisor_snapshot

app = v14.app
commercial = v14.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v15-deterministic-continuation"

_PAGE_SIZE = 6
_CONTINUATION_RE = re.compile(
    r"(?:ver|muestra(?:me)?|ensena(?:me)?|dame|quiero)\s+(?:las\s+)?(?:siguientes\s+)?(?:otras?\s+)?(?:6|seis)\s+(?:mas\s+)?(?:opciones?|carros?|vehiculos?)?|"
    r"(?:siguientes|otras?)\s+(?:6|seis)|(?:ver|mostrar)\s+(?:6|seis)\s+mas",
    re.I,
)


def _norm(value: Any) -> str:
    s = unicodedata.normalize("NFKD", str(value or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip()


def _latest(body) -> str:
    return v14._latest(body)


def _key(car: dict):
    return v14._key(car)


def _is_continuation(latest: str) -> bool:
    n = _norm(latest)
    if _CONTINUATION_RE.search(n):
        return True
    return "sin repetir" in n and any(x in n for x in ("opcion", "carro", "vehiculo", "siguiente", "mas"))


def _profile(body, visible: list[dict]):
    try:
        profile = v14._profile(body, visible)
    except Exception:
        profile = None
    return profile


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
    card["advisor_tradeoff"] = (snap.get("tradeoffs") or [""])[0]
    return card


def _continuation(body) -> dict | None:
    if body is None:
        return None
    latest = _latest(body)
    if not _is_continuation(latest):
        return None

    shown = v14._unique(list(getattr(body, "shown_cars", None) or []))
    if not shown:
        return None
    profile = _profile(body, shown)
    if profile is None:
        return None

    country = getattr(body, "country", None)
    try:
        pool = list(commercial.legacy._carly_inventory(profile, country=country) or [])
    except Exception:
        return None

    seen = {_key(car) for car in shown}
    remaining = [car for car in v14._unique(pool) if _key(car) not in seen]
    ranked = sorted(remaining, key=lambda car: advisor_score(car, profile), reverse=True)
    page_rows = ranked[:_PAGE_SIZE]

    if not page_rows:
        return {
            "phase": "conversation",
            "reply": "Ya agoté las opciones que mantienen estos criterios en el inventario confirmado actual. Puedo ampliar un criterio de forma controlada si quieres seguir buscando.",
            "token_path": "deterministic_continuation",
            "llm_calls": 0,
            "continuation_exhausted": True,
            "more_options_available": False,
            "more_options_count": 0,
            "clear_recommendations": False,
        }

    cards = [_card(row, profile, idx + 1) for idx, row in enumerate(page_rows)]
    left = max(0, len(ranked) - len(page_rows))
    reply = (
        f"Encontré {len(cards)} opciones adicionales que mantienen tus criterios y no repiten las anteriores."
        + (f" Quedan {left} más que todavía pasan el filtro." if left else " Estas son las últimas que pasan el filtro actual.")
    )
    return {
        "phase": "recommendation",
        "reply": reply,
        "recommendations": cards,
        "explore": [],
        "favorite": cards[0] if cards else None,
        "recommendation_count": len(cards),
        "explore_count": 0,
        "pool_size": len(pool),
        "quality_candidate_count": len(ranked),
        "more_options_available": left > 0,
        "more_options_count": left,
        "option_count_semantics": "remaining_eligible_after_seen_exclusion",
        "replace_recommendations": True,
        "append_recommendations": False,
        "clear_recommendations": False,
        "pagination_page_size": _PAGE_SIZE,
        "pagination_seen_count": len(seen),
        "token_path": "deterministic_continuation",
        "llm_calls": 0,
        "advisor_mode": "market_continuation_v15",
    }


def _patch() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        prior = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if prior is None or dependant is None:
            continue

        def endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = commercial._request_body(args, kwargs)
            direct = _continuation(body)
            if direct is not None:
                return direct
            return __prior(*args, **kwargs)

        route.endpoint = endpoint
        dependant.call = endpoint
        break


_patch()
