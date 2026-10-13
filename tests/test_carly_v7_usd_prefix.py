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
