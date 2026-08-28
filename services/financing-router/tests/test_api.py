from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def payload():
    return {
        "cartrade_reference": "ct_123",
        "buyer": {
            "external_id": "buyer_123",
            "country": "SV",
            "monthly_income": {"amount": 250000, "currency": "USD"},
            "monthly_debt": {"amount": 30000, "currency": "USD"},
        },
        "vehicle": {
            "external_id": "vehicle_123",
            "make": "Toyota",
            "model": "RAV4",
            "year": 2022,
            "price": {"amount": 1500000, "currency": "USD"},
            "mileage_km": 42000,
        },
        "down_payment": {"amount": 300000, "currency": "USD"},
        "requested_amount": {"amount": 1200000, "currency": "USD"},
        "consent_reference": "consent_123",
    }


def test_application_to_accepted_offer():
    created = client.post(
        "/v1/applications",
        headers={"Idempotency-Key": "test-key-123"},
        json=payload(),
    )
    assert created.status_code == 201
    application_id = created.json()["id"]

    submitted = client.post(f"/v1/applications/{application_id}/submit")
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "offered"
    offer_id = submitted.json()["offers"][0]["id"]

    accepted = client.post(
        f"/v1/applications/{application_id}/offers/{offer_id}/accept"
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"


def test_idempotency_replays_same_application():
    headers = {"Idempotency-Key": "same-key-456"}
    first = client.post("/v1/applications", headers=headers, json=payload())
    second = client.post("/v1/applications", headers=headers, json=payload())
    assert first.json()["id"] == second.json()["id"]
