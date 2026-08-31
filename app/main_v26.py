"""Carly v26: robust zero-token intake normalization.

Fixes the concrete live regressions seen in work-pickup journeys without adding
LLM calls:
- field/construction/material-hauling language is treated as work_vehicle;
- plural/heavy cargo language is recognized;
- compact monthly ranges such as ``450-600`` are interpreted as a monthly range
  when the preceding question is about budget/payment, or when the reply says
  ``al mes`` explicitly;
- the low end of a monthly range becomes the target and the high end the ceiling.

The v25 Router SHADOW pilot and all financing safety boundaries remain unchanged.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import main_v25 as v25
from . import main_preview as preview


app = v25.app
v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v26-intake-performance"


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
    return re.sub(r"\s+", " ", text).strip()


_WORK_RE = re.compile(
    r"\b(?:trabajar|trabajo|campo|finca|fincas|rural|agricultur[ao]|agricola|"
    r"ganaderia|ganadero|terraceria|ripio|escombro(?:s)?|grava|arena|cemento|"
    r"material(?:es)?|carga(?:s)?|carga(?:s)?\s+pesad(?:a|as)|trabajo\s+pesado|"
    r"obra(?:s)?|construccion|sitios?\s+de\s+construccion|herramientas|"
    r"camino(?:s)?\s+de\s+tierra|terreno(?:s)?\s+(?:rural|irregular|dificil))\b",
    re.I,
)

_MONTHLY_CONTEXT_RE = re.compile(
    r"\b(?:cuota|mensual|mensualidad|al mes|por mes|/mes|presupuesto|precio total)\b",
    re.I,
)
_RANGE_RE = re.compile(
    r"^\s*\$?\s*([0-9]{2,4})\s*(?:-|–|—|a|hasta)\s*\$?\s*([0-9]{2,4})"
    r"\s*(?:usd|dolares|dólares)?\s*(?:(al|por)\s+mes|mensual(?:es)?)?\s*$",
    re.I,
)


def _monthly_range(messages: list[Any] | None) -> tuple[float, float] | None:
    rows = list(messages or [])
    previous_role = ""
    previous_text = ""
    found = None
    for message in rows:
        role = _role(message)
        text = _content(message).strip()
        if role == "user":
            match = _RANGE_RE.match(text)
            if match:
                lo, hi = sorted((float(match.group(1)), float(match.group(2))))
                explicit_monthly = bool(match.group(3)) or "mensual" in _norm(text)
                contextual_monthly = previous_role == "assistant" and bool(_MONTHLY_CONTEXT_RE.search(previous_text))
                # A total vehicle price below $2k is not plausible for CarTrade's
                # current markets; this keeps the ambiguous 'budget' prompt useful.
                if 25 <= lo <= hi < 2000 and (explicit_monthly or contextual_monthly):
                    found = (lo, hi)
        previous_role, previous_text = role, text
    return found


def _augment_intake(messages: list[Any] | None) -> list[dict[str, str]]:
    rows = [{"role": _role(m), "content": _content(m)} for m in (messages or [])]
    monthly_range = _monthly_range(rows)

    previous_role = ""
    previous_text = ""
    for idx, row in enumerate(rows):
        if row["role"] != "user":
            previous_role, previous_text = row["role"], row["content"]
            continue

        hints: list[str] = []
        if _WORK_RE.search(row["content"]):
            hints.append("vehiculo de trabajo materiales carga trabajo pesado")

        match = _RANGE_RE.match(row["content"].strip())
        if match and monthly_range is not None:
            lo, hi = monthly_range
            hints.append(f"cuota maxima {int(hi)} al mes")

        if hints:
            row["content"] = row["content"] + "\n[parser hint: " + "; ".join(hints) + "]"
        previous_role, previous_text = row["role"], row["content"]
    return rows


_prior_extract_fast_profile = preview.extract_fast_profile
_prior_deterministic_reply = preview.deterministic_intake_reply


def _v26_extract_fast_profile(messages: list[Any] | None, country: str | None = None):
    rng = _monthly_range(messages)
    profile = _prior_extract_fast_profile(_augment_intake(messages), country=country)
    if profile and rng is not None:
        profile = dict(profile)
        profile["target_monthly"] = rng[0]
        profile["max_monthly"] = rng[1]
    return profile


def _v26_deterministic_reply(messages: list[Any] | None, country: str | None = None):
    return _prior_deterministic_reply(_augment_intake(messages), country=country)


preview.extract_fast_profile = _v26_extract_fast_profile
preview.deterministic_intake_reply = _v26_deterministic_reply
