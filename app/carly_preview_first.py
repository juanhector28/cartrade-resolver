"""Pure preview-first policy for Carly's pre-shortlist intake.

The product goal is time-to-value: show a useful first market preview before
asking the buyer to complete a perfect profile. Unknown preferences can be
refined after cards are visible.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def _text(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "")
    return str(getattr(message, "role", "") or "")


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value.lower()).strip()


def assistant_question_turns(messages: list[Any] | None) -> int:
    """Count actual pre-shortlist question turns, not every assistant message."""
    count = 0
    for message in messages or []:
        if _role(message).lower() != "assistant":
            continue
        text = _text(message)
        if "?" in text or "¿" in text:
            count += 1
    return count


def combined_user_text(messages: list[Any] | None) -> str:
    return "\n".join(
        _text(m) for m in (messages or []) if _role(m).lower() == "user"
    ).strip()


_BUDGET_RE = re.compile(
    r"(?:\$\s*\d|\b\d[\d.,]*\s*(?:usd|dolares?|dólares?)\b|"
    r"\b(?:presupuesto|budget|cuota|mensual|al\s+mes|precio\s+total|total|"
    r"maximo|máximo|tope|hasta)\b.{0,40}\d)",
    re.I,
)
_DOWN_PAYMENT_RE = re.compile(r"\b(?:prima|enganche|inicial|down\s*payment)\b", re.I)
_AFFORDABILITY_RE = re.compile(
    r"\b(?:presupuesto|budget|cuota|mensual|al\s+mes|precio\s+total|"
    r"maximo|máximo|tope|hasta)\b|/\s*mes\b",
    re.I,
)
_INTENT_RE = re.compile(
    r"\b(?:quiero|busco|necesito|carro|auto|vehiculo|vehículo|suv|sedan|sedán|"
    r"pickup|camioneta|familia|hijos?|bebe|bebé|trabajo|negocio|universidad|uni|"
    r"carretera|viajes?|ciudad|primer\s+(?:carro|auto)|prado|hilux|corolla|"
    r"civic|sentra|swift|yaris|tucson|sportage|l200|ranger|frontier)\b",
    re.I,
)


def has_budget_signal(messages: list[Any] | None) -> bool:
    """A real affordability ceiling, not merely cash available for a down payment."""
    text = combined_user_text(messages)
    # "Tengo $3,000 de prima" is useful context, but it does not tell Carly what
    # total price or monthly payment the buyer can actually afford. Ask once for
    # that missing ceiling instead of pretending the down payment is the budget.
    if _DOWN_PAYMENT_RE.search(text) and not _AFFORDABILITY_RE.search(text):
        return False
    return bool(_BUDGET_RE.search(text))


def has_intent_signal(messages: list[Any] | None) -> bool:
    text = combined_user_text(messages)
    if _INTENT_RE.search(text):
        return True
    # A substantive first-person request is enough to count as purchase intent.
    n = _norm(text)
    return len(n.split()) >= 6 and any(x in n for x in ("quiero ", "busco ", "necesito "))


def preview_policy(messages: list[Any] | None, has_visible_cars: bool = False) -> dict:
    """Return whether runtime must stop asking and materialize a first preview.

    Target behavior:
    - prefer 0-2 questions before showing market;
    - a third question is allowed only when budget or use/intent is still missing;
    - a fourth pre-preview question is never allowed.
    """
    questions = assistant_question_turns(messages)
    budget = has_budget_signal(messages)
    intent = has_intent_signal(messages)

    if has_visible_cars:
        return {
            "force_preview": False,
            "reason": "already_has_market",
            "questions": questions,
            "budget_signal": budget,
            "intent_signal": intent,
        }

    if questions >= 3:
        force, reason = True, "hard_cap_three_questions"
    elif questions >= 2 and budget and intent:
        force, reason = True, "target_two_questions"
    elif questions >= 1 and budget and intent:
        force, reason = True, "enough_information_early"
    else:
        force, reason = False, "one_blocker_may_remain"

    return {
        "force_preview": force,
        "reason": reason,
        "questions": questions,
        "budget_signal": budget,
        "intent_signal": intent,
    }
