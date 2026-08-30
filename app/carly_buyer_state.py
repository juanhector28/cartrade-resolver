"""Canonical conversational state for Carly.

The language model may interpret nuanced buyer language, but question routing must
not depend on matching an ever-growing list of phrases. This module reconstructs
which intake slots have already been answered from the conversation itself and
provides a compact state contract for downstream routing.
"""
from __future__ import annotations

import re
from typing import Any

from . import carly_fastpath

_USE_QUESTION = re.compile(r"(?:para qu[eé].{0,35}(?:usar[ií]as|usar[aá]s|quieres|necesitas)|uso principal|principalmente)", re.I)
_PASSENGER_QUESTION = re.compile(r"(?:cu[aá]ntas? personas|cu[aá]ntos? (?:viajan|pasajeros)|personas viajan)", re.I)
_BUDGET_QUESTION = re.compile(r"(?:presupuesto|cuota|precio total|techo).*[?]|[?].*(?:presupuesto|cuota|precio)", re.I | re.S)
_META_ANSWER = re.compile(r"^(?:ya te lo dije|ya lo dije|te lo dije|eso ya te lo dije|ya respond[ií]|lo respond[ií])\.?$", re.I)


def _role(m: Any) -> str:
    return str(m.get("role") if isinstance(m, dict) else getattr(m, "role", "") or "").lower()


def _content(m: Any) -> str:
    return str(m.get("content") if isinstance(m, dict) else getattr(m, "content", "") or "").strip()


def _answer_after(messages: list[Any], question_re: re.Pattern) -> str | None:
    """Return the latest substantive user answer to a known slot question."""
    waiting = False
    answer = None
    for m in messages or []:
        role, text = _role(m), _content(m)
        if role == "assistant":
            waiting = bool(question_re.search(text))
        elif role == "user" and waiting:
            if text and not _META_ANSWER.match(text):
                answer = text
            waiting = False
    return answer


def build_buyer_state(messages: list[Any] | None, country: str | None = None) -> dict:
    rows = list(messages or [])
    cheap = carly_fastpath.intake_state(rows, country=country)
    primary_use_answer = _answer_after(rows, _USE_QUESTION)
    passenger_answer = _answer_after(rows, _PASSENGER_QUESTION)
    budget_answer = _answer_after(rows, _BUDGET_QUESTION)

    # A slot is satisfied either because deterministic extraction understood its
    # value or because Carly explicitly asked that slot and received a substantive
    # answer. The latter is intentionally semantic-agnostic: language understanding
    # belongs to the interpreter, not to question routing.
    use_known = bool(cheap.get("intent_known") or primary_use_answer)
    budget_known = bool(cheap.get("budget_known") or budget_answer)

    return {
        "primary_use_known": use_known,
        "primary_use_answer": primary_use_answer,
        "budget_known": budget_known,
        "budget_answer": budget_answer,
        "passengers_known": bool(passenger_answer),
        "passengers_answer": passenger_answer,
        "max_monthly": cheap.get("max_monthly"),
        "max_price": cheap.get("max_price"),
        "job": cheap.get("job"),
        "usage": cheap.get("usage"),
        "country": cheap.get("country"),
    }


def next_blocker(messages: list[Any] | None, country: str | None = None) -> str | None:
    """Ask only for genuinely unanswered required intake slots."""
    state = build_buyer_state(messages, country=country)
    if state["primary_use_known"] and not state["budget_known"]:
        return "¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."
    if state["budget_known"] and not state["primary_use_known"]:
        return "Perfecto. ¿Para qué usarías el carro principalmente?"
    return None
