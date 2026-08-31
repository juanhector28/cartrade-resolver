import unittest

from pydantic import ValidationError

from app.financing_intake_bridge import (
    CustomerFinancingIntake,
    FinancingIntakeBridge,
    FinancingIntakeBridgeError,
    FinancingIntakeNotFound,
)


PAYLOAD = {
    "journey_id": "journey_demo_0001",
    "country": "sv",
    "borrower": {
        "full_name": "Synthetic Applicant",
        "monthly_income_reported": 1650,
        "monthly_debt": 95,
    },
    "vehicle": {
        "vehicle_ref": "inventory:demo-001",
        "make": "Toyota",
        "model": "Corolla",
        "year": 2021,
        "purchase_price": 11200,
        "market_value": 11400,
    },
    "financing": {
        "down_payment": 1700,
        "term_months": 60,
        "currency": "usd",
    },
    "consents": [{"type": "financing_prequalification", "accepted": True}],
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

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.response


class FinancingIntakeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.body = CustomerFinancingIntake.model_validate(PAYLOAD)

    def test_customer_contract_forbids_verified_and_lender_owned_facts(self):
        invalid = dict(PAYLOAD)
        invalid["borrower"] = dict(PAYLOAD["borrower"], monthly_income_verified=1590)
        invalid["financing"] = dict(PAYLOAD["financing"], annual_rate_pct=15.5)
        invalid["checks"] = {"bureau_score": 702, "fraud_score": 17}
        with self.assertRaises(ValidationError):
            CustomerFinancingIntake.model_validate(invalid)

    def test_idempotency_is_stable_and_user_scoped(self):
        a = FinancingIntakeBridge.idempotency_key("user-a", self.body.journey_id, self.body.vehicle.vehicle_ref)
        replay = FinancingIntakeBridge.idempotency_key("user-a", self.body.journey_id, self.body.vehicle.vehicle_ref)
        b = FinancingIntakeBridge.idempotency_key("user-b", self.body.journey_id, self.body.vehicle.vehicle_ref)
        self.assertEqual(a, replay)
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("webint:"))

    def test_submit_injects_authenticated_user_and_stops_before_router(self):
        response = FakeResponse(payload={
            "financing_intake_id": "ct_int_1",
            "journey_id": self.body.journey_id,
            "vehicle_ref": self.body.vehicle.vehicle_ref,
            "state": "CHECKS_PENDING",
            "requested_amount": 9500,
            "currency": "USD",
            "next_required": ["identity", "income_verification", "bureau", "fraud"],
            "router_submitted": False,
            "integration_mode": "SHADOW",
            "contractual": False,
        })
        client = FakeClient(response)
        bridge = FinancingIntakeBridge(api_key="x" * 40, client=client)
        result = bridge.submit(user_id="supabase-user-1", body=self.body)

        self.assertEqual(result["status"], "CHECKS_PENDING")
        self.assertFalse(result["router_submitted"])
        self.assertFalse(result["displayable_approval"])
        self.assertEqual(len(client.calls), 1)
        method, path, call = client.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/v1/financing/intakes")
        self.assertEqual(call["json"]["user_subject"], "supabase-user-1")
        self.assertNotIn("checks", call["json"])
        self.assertNotIn("monthly_income_verified", call["json"]["borrower"])
        self.assertNotIn("annual_rate_pct", call["json"]["financing"])
        self.assertIn("Authorization", call["headers"])
        self.assertIn("Idempotency-Key", call["headers"])

    def test_owner_can_read_customer_safe_status(self):
        user_id = "supabase-user-1"
        response = FakeResponse(payload={
            "financing_intake_id": "ct_int_1",
            "journey_id": self.body.journey_id,
            "vehicle_ref": self.body.vehicle.vehicle_ref,
            "state": "CHECKS_PENDING",
            "requested_amount": 9500,
            "currency": "USD",
            "next_required": ["identity", "income_verification", "bureau", "fraud"],
            "owner_subject_hash": FinancingIntakeBridge.owner_subject_hash(user_id),
            "router_submitted": False,
            "integration_mode": "SHADOW",
            "contractual": False,
        })
        bridge = FinancingIntakeBridge(api_key="x" * 40, client=FakeClient(response))
        result = bridge.get(user_id=user_id, intake_id="ct_int_1")
        self.assertEqual(result["status"], "CHECKS_PENDING")
        self.assertEqual(result["next_required"], ["identity", "income_verification", "bureau", "fraud"])
        self.assertNotIn("owner_subject_hash", result)

    def test_non_owner_get_is_indistinguishable_from_missing(self):
        response = FakeResponse(payload={
            "financing_intake_id": "ct_int_1",
            "state": "CHECKS_PENDING",
            "owner_subject_hash": FinancingIntakeBridge.owner_subject_hash("someone-else"),
            "router_submitted": False,
            "integration_mode": "SHADOW",
            "contractual": False,
        })
        bridge = FinancingIntakeBridge(api_key="x" * 40, client=FakeClient(response))
        with self.assertRaises(FinancingIntakeNotFound):
            bridge.get(user_id="supabase-user-1", intake_id="ct_int_1")

    def test_rejects_any_response_that_crosses_router_boundary(self):
        response = FakeResponse(payload={
            "state": "CHECKS_PENDING",
            "router_submitted": True,
            "integration_mode": "SHADOW",
            "contractual": False,
        })
        bridge = FinancingIntakeBridge(api_key="x" * 40, client=FakeClient(response))
        with self.assertRaises(FinancingIntakeBridgeError):
            bridge.submit(user_id="user-a", body=self.body)


if __name__ == "__main__":
    unittest.main()
