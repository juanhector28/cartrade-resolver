import os
import unittest
from unittest.mock import patch

from app.financing_intake_bridge import CustomerFinancingIntake
from app.pilot_financing_promoter import (
    PILOT_EVIDENCE_MODE,
    build_synthetic_shadow_journey,
    mirror_intake_to_router_shadow,
    pilot_autopromote_enabled,
)


PAYLOAD = {
    "journey_id": "journey_pilot_0001",
    "country": "SV",
    "borrower": {
        "full_name": "Pilot Applicant",
        "monthly_income_reported": 1800,
        "monthly_debt": 100,
    },
    "vehicle": {
        "vehicle_ref": "inventory:pilot-001",
        "make": "Toyota",
        "model": "Corolla",
        "year": 2022,
        "purchase_price": 12000,
        "market_value": 12200,
    },
    "financing": {
        "down_payment": 2000,
        "term_months": 60,
        "currency": "USD",
    },
    "consents": [{"type": "financing_prequalification", "accepted": True}],
    "trust_credentials": [],
}


class FakeBridge:
    def __init__(self):
        self.calls = []

    def submit(self, *, user_id, body):
        self.calls.append((user_id, body))
        return {
            "status": "ROUTER_SUBMITTED",
            "financing_request_id": "ct_fin_1",
            "router_application_id": "rt_app_1",
            "shadow_recommendation": "APPROVAL_PENDING",
            "policy_version": "3.4",
            "integration_mode": "SHADOW",
            "contractual": False,
        }


class PilotFinancingPromoterTests(unittest.TestCase):
    def setUp(self):
        self.body = CustomerFinancingIntake.model_validate(PAYLOAD)

    def test_defaults_on_only_for_sandbox_lender(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(pilot_autopromote_enabled())
        with patch.dict(os.environ, {"CARTRADE_FINANCING_INSTITUTION_ID": "real_bank"}, clear=True):
            self.assertFalse(pilot_autopromote_enabled())
        with patch.dict(
            os.environ,
            {
                "CARTRADE_FINANCING_INSTITUTION_ID": "sandbox_lender",
                "CARTRADE_PILOT_ROUTER_AUTOPROMOTE": "0",
            },
            clear=True,
        ):
            self.assertFalse(pilot_autopromote_enabled())

    def test_builds_explicit_synthetic_shadow_evidence(self):
        with patch.dict(os.environ, {}, clear=True):
            journey = build_synthetic_shadow_journey(self.body)
        self.assertEqual(journey.borrower.monthly_income_verified, 1800)
        self.assertEqual(journey.financing.requested_amount, 10000)
        self.assertEqual(journey.financing.annual_rate_pct, 14.0)
        self.assertEqual(journey.checks.bureau_score, 710)
        self.assertEqual(journey.checks.fraud_score, 10.0)
        self.assertEqual(getattr(journey.vehicle, "evidence_mode"), PILOT_EVIDENCE_MODE)
        markers = [c for c in journey.consents if c.get("type") == "pilot_synthetic_evidence"]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["scope"], "router_shadow_non_contractual")

    def test_mirror_calls_existing_financing_bridge_once(self):
        bridge = FakeBridge()
        with patch.dict(os.environ, {}, clear=True):
            result = mirror_intake_to_router_shadow(
                user_id="supabase-user-1",
                body=self.body,
                bridge=bridge,
            )
        self.assertEqual(len(bridge.calls), 1)
        self.assertEqual(result["status"], "ROUTER_SHADOW_SUBMITTED")
        self.assertEqual(result["router_application_id"], "rt_app_1")
        self.assertEqual(result["evidence_mode"], PILOT_EVIDENCE_MODE)
        self.assertFalse(result["contractual"])

    def test_real_lender_route_is_fail_closed(self):
        bridge = FakeBridge()
        with patch.dict(os.environ, {"CARTRADE_FINANCING_INSTITUTION_ID": "bank_prod"}, clear=True):
            result = mirror_intake_to_router_shadow(
                user_id="supabase-user-1",
                body=self.body,
                bridge=bridge,
            )
        self.assertIsNone(result)
        self.assertEqual(bridge.calls, [])


if __name__ == "__main__":
    unittest.main()
