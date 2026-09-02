"""Carly v35: retain explicit session facts across intake turns.

Targeted fix for two demo-visible issues:
- a standalone large amount after a mixed "precio total o cuota" question is
  classified as total purchase budget by magnitude;
- passenger counts such as "somos 5, incluyendo un bebé" remain known across
  turns and cannot trigger a redundant passenger question.
"""
from __future__ import annotations

import re
from typing import Any

from . import carly_fastpath as fastpath
from . import main_preview as preview
from . import main_v34 as v34

app = v34.app

_ORIG_MAX_PRICE = fastpath._max_price_from_messages
_ORIG_EXTRACT_FAST_PROFILE = fastpath.extract_fast_profile

try:
    v34.v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v35-session-facts"
except Exception:
    pass

_BUDGET_QUESTION = re.compile(
    r"\b(?:presupuesto|precio|precio total|total|cuota|mensual|mensualidad|tope|techo|maximo|máximo)\b",
    re.I,
)
_PASSENGER_WORDS = {
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
}
_PASSENGERS = re.compile(
    r"\b(?:somos|viajamos|viajan|seremos|familia\s+de)\s+"
    r"(?P<count>\d{1,2}|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve)"
    r"(?:\s+(?:personas|pasajeros|adultos))?\b",
    re.I,
)


def _mixed_question_total_budget(messages: list[Any] | None) -> float | None:
    previous_role = ""
    previous_text = ""
    value = None
    for message in messages or []:
        role = fastpath._role(message).lower()
        text = fastpath._content(message).strip()
        if role == "user":
            standalone = fastpath._STANDALONE_MONEY.match(text)
            if standalone and previous_role == "assistant" and _BUDGET_QUESTION.search(previous_text):
                parsed = fastpath._parse_number(standalone.group(1), standalone.group(2))
                # Magnitude disambiguates a mixed total-vs-monthly question.
                if parsed is not None and 2000 <= parsed <= 500_000:
                    value = parsed
        previous_role, previous_text = role, text
    return value


def _max_price_from_messages(messages: list[Any] | None) -> float | None:
    value = _ORIG_MAX_PRICE(messages)
    return value if value is not None else _mixed_question_total_budget(messages)


def _passenger_count(messages: list[Any] | None) -> int | None:
    text = fastpath.user_text(messages)
    found = None
    for match in _PASSENGERS.finditer(text):
        raw = fastpath._norm(match.group("count"))
        try:
            parsed = int(raw)
        except ValueError:
            parsed = _PASSENGER_WORDS.get(raw)
        if parsed is not None and 1 <= parsed <= 20:
            found = parsed
    return found


def _extract_fast_profile(messages: list[Any] | None, country: str | None = None) -> dict | None:
    data = _ORIG_EXTRACT_FAST_PROFILE(messages, country=country)
    if not isinstance(data, dict):
        return data
    passengers = _passenger_count(messages)
    if passengers is not None:
        data["passengers"] = passengers
    return data


# The original extractor resolves _max_price_from_messages through its module
# globals, so patch budget parsing first, then expose the wrapped profile parser
# to both direct users and main_preview's imported global reference.
fastpath._max_price_from_messages = _max_price_from_messages
fastpath.extract_fast_profile = _extract_fast_profile
preview.extract_fast_profile = _extract_fast_profile
