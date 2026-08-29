"""Carly v7 composition root.

The frontend can persist ``shown_cars`` from an older decision even while the
visible chat has started a fresh intake.  v6 treated any non-empty shown_cars as
proof that the buyer was in follow-up mode, which blocked the zero-token intake
fastpath and caused a plain ``500`` budget answer to be asked again.

This wrapper only clears those cards for high-confidence intake turns. Normal
post-shortlist questions continue to receive the visible cards unchanged.
"""
from __future__ import annotations

import re
from typing import Any

from . import main_commercial as commercial

app = commercial.app
commercial.RUNTIME_COMPOSITION = "commercial-v7-stale-state"

_FRESH_MISSION_RE = re.compile(
    r"\b(?:busco|estoy\s+buscando|quiero|necesito)\b.{0,100}"
    r"\b(?:carro|auto|veh[ií]culo|compact[oa]|pickup|pick-up|suv|sed[aá]n|"
    r"hatch(?:back)?|ciudad|urbano|familia|trabajo|delivery|reparto|carretera)\b",
    re.I | re.S,
)
_BUDGET_REPLY_RE = re.compile(
    r"^\s*(?:\$?\s*\d+(?:[.,]\d+)?\s*(?:usd|d[oó]lares?)?|"
    r"\$?\s*\d+(?:[.,]\d+)?\s*(?:/\s*mes|al\s+mes|por\s+mes|mensuales?))\s*$",
    re.I,
)


def _role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "").lower()
    return str(getattr(message, "role", "") or "").lower()


def _content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _latest_user_text(messages: list[Any]) -> str:
    for message in reversed(list(messages or [])):
        if _role(message) == "user":
            return _content(message).strip()
    return ""


def _is_high_confidence_intake_turn(messages: list[Any], country: str | None = None) -> bool:
    """True only when stale visible cards should not force follow-up mode."""
    rows = list(messages or [])
    latest = _latest_user_text(rows)
    if not latest:
        return False

    # A fresh mission should always be allowed to start clean, even if the UI
    # accidentally carries cards from the previous decision.
    if _FRESH_MISSION_RE.search(latest):
        blocker = commercial.preview.deterministic_intake_reply(rows, country=country)
        fast = commercial.preview.extract_fast_profile(rows, country=country)
        return blocker is not None or fast is not None

    # For a short budget reply, reconstruct the omitted assistant question using
    # the v6 repair. If that yields a complete profile, this is definitely intake,
    # not a question about one of the stale cards.
    if _BUDGET_REPLY_RE.match(latest):
        repaired = commercial._repair_missing_monthly_context(rows, country=country)
        return commercial.preview.extract_fast_profile(repaired, country=country) is not None

    return False


def _patch_stale_card_intake() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue
        prior = endpoint

        def v7_endpoint(*args: Any, __prior=prior, **kwargs: Any):
            body = commercial._request_body(args, kwargs)
            if body is not None and (getattr(body, "shown_cars", None) or []):
                messages = list(getattr(body, "messages", None) or [])
                country = getattr(body, "country", None)
                if _is_high_confidence_intake_turn(messages, country=country):
                    # Historical cards are not evidence for the new decision.
                    body.shown_cars = None
            return __prior(*args, **kwargs)

        route.endpoint = v7_endpoint
        dependant.call = v7_endpoint
        break


_patch_stale_card_intake()
