"""Small deterministic UI/context rules for Carly.

The backend is authoritative about when a real market comparison happened and
about whether a buyer message refers to a card already present in context.
Keeping these rules dependency-free makes them easy to regression-test.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def norm_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def phrase_in(text: Any, phrase: Any) -> bool:
    t = norm_text(text)
    p = norm_text(phrase)
    return bool(p and f" {p} " in f" {t} ")


def message_names_car(text: str, car: Mapping[str, Any]) -> bool:
    """True when a buyer turn names a visible make/model/year unambiguously enough."""
    model = car.get("model")
    year = car.get("year")
    if not model or not year:
        return False
    if not phrase_in(text, model) or str(year) not in str(text or ""):
        return False
    make = car.get("make")
    # Model + year is sufficient. Make, when present, strengthens the match but is
    # not required because UI-generated prompts sometimes omit it.
    return True if not make else (phrase_in(text, make) or phrase_in(text, model))


def requested_year(text: str) -> int | None:
    match = _YEAR_RE.search(str(text or ""))
    return int(match.group(0)) if match else None


def should_show_market_animation(result: Mapping[str, Any] | None) -> bool:
    """Animation only belongs to a turn that actually materialized a new shortlist."""
    if not isinstance(result, Mapping):
        return False
    return bool(
        result.get("phase") == "recommendation"
        and result.get("recommendations")
        and result.get("decision_state") != "rebuilding"
    )


def apply_ui_contract(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    searched = should_show_market_animation(result)
    result["show_market_animation"] = searched
    result["market_search_performed"] = searched
    # Frontend contract: every card the buyer can currently click or ask about,
    # including newly revealed explore cards, belongs in shown_cars on follow-ups.
    result["shown_cars_scope"] = "all_visible_cards"
    return result
