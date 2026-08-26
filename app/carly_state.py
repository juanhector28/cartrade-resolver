"""Deterministic conversation-state rules for Carly.

A buyer can explicitly change missions after a shortlist. When that happens,
previous recommendation cards are historical context, not active decision evidence.
This module is intentionally dependency-free so the state rules are easy to test.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

_PROFILE_RESET_RE = re.compile(
    r"\b(?:"
    r"cambiando\s+lo\s+que\s+busco|cambio\s+lo\s+que\s+busco|"
    r"quiero\s+cambiar\s+lo\s+que\s+busco|quiero\s+algo\s+diferente|"
    r"busco\s+algo\s+diferente|empecemos\s+de\s+cero|empezamos\s+de\s+cero|"
    r"partamos\s+de\s+cero|partimos\s+de\s+cero|nuevo\s+perfil|"
    r"otra\s+necesidad|otro\s+tipo\s+de\s+carro|segundo\s+carro"
    r")\b",
    re.I,
)

_FRESH_RECOMMENDATION_RE = re.compile(
    r"\b(?:estoy\s+optimizando\s+para|de\s+todo\s+lo\s+que\s+cruc[eé])\b",
    re.I,
)


def _role(message: Any) -> str:
    if isinstance(message, Mapping):
        return str(message.get("role") or "").lower()
    return str(getattr(message, "role", "") or "").lower()


def _content(message: Any) -> str:
    if isinstance(message, Mapping):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def is_profile_reset_text(text: str) -> bool:
    return bool(_PROFILE_RESET_RE.search(str(text or "")))


def has_unresolved_decision_reset(messages: Iterable[Any]) -> bool:
    """True after an explicit mission reset until a fresh shortlist is emitted."""
    reset_index = None
    materialized = list(messages or [])
    for idx, message in enumerate(materialized):
        if _role(message) == "user" and is_profile_reset_text(_content(message)):
            reset_index = idx

    if reset_index is None:
        return False

    for message in materialized[reset_index + 1:]:
        if _role(message) == "assistant" and _FRESH_RECOMMENDATION_RE.search(_content(message)):
            return False
    return True


def latest_user_resets_decision(messages: Iterable[Any]) -> bool:
    for message in reversed(list(messages or [])):
        if _role(message) == "user":
            return is_profile_reset_text(_content(message))
    return False
