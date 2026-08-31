import os
import unittest
from unittest.mock import patch

from app.financing_bridge import FinancingBridge, FinancingBridgeError, FinancingJourneyInput


PAYLOAD = {
    "journey_id": "journey_demo_0001",
    "country": "sv",
    "borrower": {
        "full_name": "Synthetic Applicant",
        "monthly_income_reported": 1650,
        "monthly_income_verified": 1590,
        "monthly_debt": 95,
    },
    "vehicle": {
        "vehicle_ref": "inventory:demo-001",
        "make": "Toyota",
        "model": "Corolla",
        "year": 2021,
        "purchase_price": 11200,
        "market_value": 11400,
        "vin_token": "trust_asset_demo_001",
    },
    "financing": {
        "requested_amount": 9500,
        "down_payment": 1700,
        "term_months": 60,
        "annual_rate_pct": 15.5,
        "currency": "usd",
    },
    "checks": {"bureau_score": 702, "fraud_score": 17},
    "consents": [],
    "trust_credentials": [],
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return self.response


class FinancingBridgeTests(unittest.TestCase):
    def setUp(self):
        self.body = FinancingJourneyInput.model_validate(PAYLOAD)

    def test_normalizes_country_and_currency(self):
        self.assertEqual(self.body.country, "SV")
        self.assertEqual(self.body.financing.currency, "USD")

    def test_route_is_server_owned(self):
        bridge = FinancingBridge(api_key="x" * 40)
        with patch.dict(os.environ, {
            "CARTRADE_FINANCING_INSTITUTION_ID": "sandbox_lender",
            "CARTRADE_FINANCING_PRODUCT_ID": "used_vehicle_standard",
        }, clear=False):
            payload = bridge.build_payload(self.body)
        self.assertEqual(payload["institution_id"], "sandbox_lender")
        self.assertEqual(payload["product_id"], "used_vehicle_standard")
        self.assertNotIn("vehicle_ref", payload["vehicle"])

    def test_idempotency_is_stable_and_user_scoped(self):
        first = FinancingBridge.idempotency_key("user-a", self.body.journey_id, self.body.vehicle.vehicle_ref)
        second = FinancingBridge.idempotency_key("user-a", self.body.journey_id, self.body.vehicle.vehicle_ref)
        other = FinancingBridge.idempotency_key("user-b", self.body.journey_id, self.body.vehicle.vehicle_ref)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertTrue(first.startswith("webfin:"))

    def test_submit_returns_safe_shadow_envelope(self):
        response = FakeResponse(payload={
            "state": "ROUTER_SHADOW_READY",
            "financing_request_id": "ct_fin_1",
            "external_application_id": "ct_fin_1",
            "router": {
                "application_id": "rt_app_1",
                "recommendation": "APPROVAL_PENDING",
                "policy_version": "shadow-pilot-v1",
                "integration_mode": "SHADOW",
                "contractual": False,
            },
        })
        client = FakeClient(response)
        bridge = FinancingBridge(api_key="x" * 40, client=client)
        result = bridge.submit(user_id="user-a", body=self.body)
        self.assertEqual(result["status"], "ROUTER_SHADOW_READY")
        self.assertFalse(result["contractual"])
        self.assertFalse(result["displayable_approval"])
        self.assertIsNone(result["borrower_approval"])
        self.assertEqual(len(client.calls), 1)
        _, call = client.calls[0]
        self.assertIn("Authorization", call["headers"])
        self.assertIn("Idempotency-Key", call["headers"])

    def test_rejects_contractual_response(self):
        response = FakeResponse(payload={
            "state": "ROUTER_SHADOW_READY",
            "router": {"integration_mode": "SHADOW", "contractual": True},
        })
        bridge = FinancingBridge(api_key="x" * 40, client=FakeClient(response))
        with self.assertRaises(FinancingBridgeError):
            bridge.submit(user_id="user-a", body=self.body)

    def test_rejects_live_response(self):
        response = FakeResponse(payload={
            "state": "READY",
            "router": {"integration_mode": "LIVE", "contractual": False},
        })
        bridge = FinancingBridge(api_key="x" * 40, client=FakeClient(response))
        with self.assertRaises(FinancingBridgeError):
            bridge.submit(user_id="user-a", body=self.body)


if __name__ == "__main__":
    unittest.main()
