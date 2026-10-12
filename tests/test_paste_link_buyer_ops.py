"""Private buyer inbox must never leak buyer contact to unauthorized callers."""
import hashlib
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import rate_limit
from app.main import app

TOKEN = "private-operator-test-token-0123456789ABCDEF"
ID = str(uuid4())
URL = "https://www.julajups.sv/anuncio/toyota-4-runner-trd-2019-4x4-N3tSneYO52"
ROW = {
    "request_id": ID, "created_at": "2026-10-12T13:00:00+00:00",
    "buyer_contact": "70000000", "contact_channel": "whatsapp",
    "listing_url": URL, "car_name": "Toyota 4Runner TRD 2019",
    "price_usd": 27500, "country": "sv", "status": "received",
    "consent_recorded_at": "2026-10-12T13:00:00+00:00",
}


class FakeQuery:
    def __init__(self, db):
        self.db = db
        self.mode = "select"
        self.id_filter = None

    def select(self, columns):
        self.db.columns = columns
        return self

    def order(self, field, desc=False):
        self.db.sorted_by = field
        return self

    def range(self, start, end):
        self.db.range_requested = (start, end)
        return self

    def update(self, fields):
        self.mode = "update"
        self.db.fields = fields
        return self

    def eq(self, name, value):
        self.id_filter = (name, value)
        return self

    def execute(self):
        if self.db.fail:
            raise RuntimeError("private database credentials / sensitive error")
        if self.mode == "update":
            if self.id_filter != ("request_id", ID):
                return type("Result", (), {"data": []})()
            self.db.row["status"] = self.db.fields["status"]
        return type("Result", (), {"data": [self.db.row.copy()]})()


class FakeDatabase:
    def __init__(self, fail=False):
        self.row = ROW.copy()
        self.fail = fail
        self.table_name = None

    def table(self, name):
        self.table_name = name
        return FakeQuery(self)


def setup(monkeypatch, db=None):
    monkeypatch.setenv("BUYER_OPS_ENABLED", "1")
    monkeypatch.setenv("BUYER_OPS_TOKEN_SHA256", hashlib.sha256(TOKEN.encode()).hexdigest())
    monkeypatch.setenv("BUYER_INTENTS_TABLE", "buyer_intents")
    monkeypatch.setattr(app.state, "buyer_intents_db", db or FakeDatabase(), raising=False)
    monkeypatch.setattr(rate_limit, "check", lambda value: (True, 10))


def client():
    # No app lifespan: unrelated startup checks need actual infrastructure.
    return TestClient(app)


def headers(token=TOKEN):
    return {"Authorization": "Bearer " + token}


def test_inbox_is_off_by_default(monkeypatch):
    monkeypatch.delenv("BUYER_OPS_ENABLED", raising=False)
    response = client().get("/ops/api/solicitudes")
    assert response.status_code == 404
    assert client().get("/ops/solicitudes").status_code == 404


def test_inbox_misconfiguration_fails_closed(monkeypatch):
    setup(monkeypatch)
    monkeypatch.delenv("BUYER_OPS_TOKEN_SHA256")
    assert client().get("/ops/api/solicitudes", headers=headers()).status_code == 503


def test_refuse_without_valid_operator_token(monkeypatch):
    setup(monkeypatch)
    for token in ("", "x" * 40, "private-operator-test-token-0123456789abcDEF"):
        response = client().get("/ops/api/solicitudes", headers=headers(token))
        assert response.status_code == 401
        assert "buyer_contact" not in response.text


def test_private_page_contains_no_customer_data(monkeypatch):
    setup(monkeypatch)
    response = client().get("/ops/solicitudes")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "70000000" not in response.text
    assert 'localStorage' not in response.text
    assert 'sessionStorage' not in response.text
    assert 'innerHTML' not in response.text


def test_authorized_list_and_update_status(monkeypatch):
    db = FakeDatabase()
    setup(monkeypatch, db)
    response = client().get("/ops/api/solicitudes?limit=20&offset=0", headers=headers())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["items"][0]["buyer_contact"] == ROW["buyer_contact"]
    assert db.table_name == "buyer_intents"
    assert db.range_requested == (0, 19)
    status = client().patch(
        "/ops/api/solicitudes/" + ID,
        json={"status": "in_review"}, headers=headers(),
    )
    assert status.status_code == 200
    assert status.json() == {"request_id": ID, "status": "in_review"}
    assert "buyer_contact" not in status.text
    assert db.row["status"] == "in_review"


def test_invalid_status_rejected(monkeypatch):
    setup(monkeypatch)
    r = client().patch(
        "/ops/api/solicitudes/" + ID,
        json={"status": "approved_financing"}, headers=headers(),
    )
    assert r.status_code == 422


def test_invalid_pagination_rejected(monkeypatch):
    setup(monkeypatch)
    assert client().get("/ops/api/solicitudes?limit=200", headers=headers()).status_code == 422


def test_sensitive_db_errors_not_exposed(monkeypatch):
    setup(monkeypatch, FakeDatabase(fail=True))
    response = client().get("/ops/api/solicitudes", headers=headers())
    assert response.status_code == 503
    assert "private database credentials" not in response.text


def test_unknown_request_not_updated(monkeypatch):
    setup(monkeypatch)
    response = client().patch(
        "/ops/api/solicitudes/" + str(uuid4()),
        json={"status": "closed"}, headers=headers(),
    )
    assert response.status_code == 404
