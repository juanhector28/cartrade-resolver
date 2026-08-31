"""Sandbox-only SHADOW mirror from financing intake to Router.

This module validates the CarTrade -> Transactions -> Router rail before real
evidence providers are connected. It must never be treated as underwriting.
Synthetic evidence is always routed to a dedicated sandbox lender, regardless of
the lender configured for the normal financing path, and every downstream
response is required to remain SHADOW / non-contractual.

When real identity, income, bureau, fraud and valuation checks exist, the trigger
should move into Transactions and call the same evidence-complete financing rail.
"""
from __future__ import annotations

import os
from typing import Any

from .financing_bridge import FinancingBridge, FinancingJourneyInput
from .financing_intake_bridge import CustomerFinancingIntake


PILOT_EVIDENCE_MODE = "synthetic_shadow"
PILOT_INSTITUTION_ID = "sandbox_lender"
PILOT_PRODUCT_ID = "used_vehicle_standard"


class SandboxPilotFinancingBridge(FinancingBridge):
    """Financing bridge whose lender route cannot escape the sandbox."""

    def _route(self) -> tuple[str, str]:
        return PILOT_INSTITUTION_ID, PILOT_PRODUCT_ID


def pilot_autopromote_enabled() -> bool:
    """Pilot is on by default and can be explicitly disabled.

    This is safe with respect to lender routing because the pilot bridge is pinned
    to sandbox_lender and cannot inherit the production financing institution.
    """
    explicit = os.getenv("CARTRADE_PILOT_ROUTER_AUTOPROMOTE", "").strip().lower()
    if not explicit:
        return True
    return explicit in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def build_synthetic_shadow_journey(body: CustomerFinancingIntake) -> FinancingJourneyInput:
    """Build deterministic, explicitly synthetic evidence for the sandbox rail.

    None of these generated facts may be rendered as verified customer data or a
    bank approval. They exist solely to exercise Router in SHADOW mode.
    """
    purchase_price = float(body.vehicle.purchase_price)
    down_payment = float(body.financing.down_payment)
    requested_amount = body.financing.requested_amount
    if requested_amount is None:
        requested_amount = max(1.0, purchase_price - down_payment)

    market_value = body.vehicle.market_value
    if market_value is None:
        market_value = purchase_price

    reported_income = float(body.borrower.monthly_income_reported)
    annual_rate_pct = _float_env("CARTRADE_PILOT_ANNUAL_RATE_PCT", 14.0)
    bureau_score = _int_env("CARTRADE_PILOT_BUREAU_SCORE", 710)
    fraud_score = _float_env("CARTRADE_PILOT_FRAUD_SCORE", 10.0)

    consents: list[dict[str, Any]] = list(body.consents)
    consents.append(
        {
            "type": "pilot_synthetic_evidence",
            "accepted": True,
            "scope": "router_shadow_non_contractual",
            "evidence_mode": PILOT_EVIDENCE_MODE,
        }
    )

    return FinancingJourneyInput.model_validate(
        {
            "journey_id": body.journey_id,
            "country": body.country,
            "borrower": {
                "full_name": body.borrower.full_name,
                "monthly_income_reported": reported_income,
                "monthly_income_verified": reported_income,
                "monthly_debt": body.borrower.monthly_debt,
            },
            "vehicle": {
                "vehicle_ref": body.vehicle.vehicle_ref,
                "make": body.vehicle.make,
                "model": body.vehicle.model,
                "year": body.vehicle.year,
                "purchase_price": purchase_price,
                "market_value": market_value,
                "evidence_mode": PILOT_EVIDENCE_MODE,
            },
            "financing": {
                "requested_amount": requested_amount,
                "down_payment": down_payment,
                "term_months": body.financing.term_months,
                "annual_rate_pct": annual_rate_pct,
                "currency": body.financing.currency,
            },
            "checks": {
                "bureau_score": bureau_score,
                "fraud_score": fraud_score,
            },
            "consents": consents,
            "trust_credentials": body.trust_credentials,
        }
    )


def mirror_intake_to_router_shadow(
    *,
    user_id: str,
    body: CustomerFinancingIntake,
    bridge: FinancingBridge | None = None,
) -> dict[str, Any] | None:
    """Submit one synthetic SHADOW twin when the sandbox pilot is enabled."""
    if not pilot_autopromote_enabled():
        return None
    journey = build_synthetic_shadow_journey(body)
    pilot_bridge = bridge or SandboxPilotFinancingBridge()
    result = pilot_bridge.submit(user_id=user_id, body=journey)
    if result.get("integration_mode") != "SHADOW" or result.get("contractual") is not False:
        raise RuntimeError("pilot financing mirror escaped SHADOW boundary")
    return {
        "status": "ROUTER_SHADOW_SUBMITTED",
        "evidence_mode": PILOT_EVIDENCE_MODE,
        "institution_id": PILOT_INSTITUTION_ID,
        "product_id": PILOT_PRODUCT_ID,
        "router_application_id": result.get("router_application_id"),
        "financing_request_id": result.get("financing_request_id"),
        "shadow_recommendation": result.get("shadow_recommendation"),
        "policy_version": result.get("policy_version"),
        "integration_mode": "SHADOW",
        "contractual": False,
    }
