"""Regression tests for the v7 stale-card intake budget guard.

A buyer can have stale shown_cars in the request while beginning a fresh
conversation. The guard must recognize the exact monetary forms that the
newer fastpath (v45) already accepts.
"""
import pytest

from app.main_v7 import _BUDGET_REPLY_RE


@pytest.mark.parametrize("reply", ["USD 600", "usd 600", "US$ 600", "$600", "600 USD", "600", "600 al mes"])
def test_stale_card_budget_guard_accepts_monthly_answer(reply):
    assert _BUDGET_REPLY_RE.fullmatch(reply), reply


@pytest.mark.parametrize("reply", ["Toyota Corolla", "600 km", "USD 600 de entrada"])
def test_stale_card_budget_guard_rejects_non_budget_message(reply):
    assert _BUDGET_REPLY_RE.fullmatch(reply) is None


def test_corolla_commute_usd_600_with_stale_cards_is_intake():
    """Reproduce the buyer's reported context, not just the regex."""
    from app.main_v7 import _is_high_confidence_intake_turn

    messages = [
        {"role": "user", "content": "Busco un Toyota Corolla usado en El Salvador"},
        {"role": "assistant", "content": "Perfecto, tomo Toyota Corolla como tu preferencia. ¿Para qué lo vas a usar principalmente?"},
        {"role": "user", "content": "Para ir al trabajo cada mañana"},
        {"role": "assistant", "content": "Perfecto. ¿Qué cuota mensual te queda cómoda?"},
        {"role": "user", "content": "USD 600"},
    ]
    assert _is_high_confidence_intake_turn(messages, country="sv") is True
