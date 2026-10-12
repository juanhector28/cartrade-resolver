"""Buyer intake must require explicit consent, isolate PII and fail closed."""
from contextlib import nullcontext
from uuid import uuid4

from fastapi.testclient import TestClient

from app import rate_limit
from app.main import app

URL = "https://www.julajups.sv/anuncio/toyota-4-runner-trd-2019-4x4-N3tSneYO52"
ORIGIN = {"Origin": "https://cartrade.live"}


class FakeQuery:
    def __init__(self, parent):
        self.parent = parent

    def upsert(self, row, on_conflict=None, ignore_duplicates=False):
        self.parent.row = row
        self.parent.conflict_key = on_conflict
        self.parent.ignore_duplicates = ignore_duplicates
        return self

    def execute(self):
        if self.parent.fail:
            raise RuntimeError("private db message")
        return type("Result", (), {"data": [self.parent.row]})()


class FakeDatabase:
    def __init__(self, fail=False):
        self.fail = fail
        self.row = None
        self.table_name = None

    def table(self, name):
        self.table_name = name
        return FakeQuery(self)


def make_payload():
    return {
        "request_id": str(uuid4()),
        "buyer_contact": "7000-0000",
        "contact_channel": "whatsapp",
        "listing_url": URL,
        "car_name": "Toyota 4Runner TRD 2019",
        "price_usd": 27500,
        "country": "sv",
        "source": "paste_link",
        "consent_to_contact": True,
    }


def setup(monkeypatch, db):
    monkeypatch.setenv("BUYER_INTENTS_ENABLED", "1")
    monkeypatch.setenv("BUYER_INTENTS_TABLE", "buyer_intents")
    monkeypatch.setattr(app.state, "buyer_intents_db", db, raising=False)
    monkeypatch.setattr(rate_limit, "check", lambda ip: (True, 9))


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("BUYER_INTENTS_ENABLED", raising=False)
    with nullcontext(TestClient(app)) as client:
        assert client.post("/buyer-intents", json=make_payload(), headers=ORIGIN).status_code == 503


def test_captures_only_consent_based_buyer_request(monkeypatch):
    db = FakeDatabase()
    setup(monkeypatch, db)
    data = make_payload()
    with nullcontext(TestClient(app)) as client:
        res = client.post("/buyer-intents", json=data, headers=ORIGIN)
    assert res.status_code == 201
    assert res.json() == {"status": "received", "request_id": data["request_id"]}
    assert res.headers["cache-control"] == "no-store"
    assert db.table_name == "buyer_intents"
    assert db.row["buyer_contact"] == "70000000"
    assert db.row["listing_url"] == URL
    assert db.row["status"] == "received"
    assert db.conflict_key == "request_id"


def test_without_consent_refused(monkeypatch):
    setup(monkeypatch, FakeDatabase())
    data = make_payload()
    data["consent_to_contact"] = False
    with nullcontext(TestClient(app)) as client:
        assert client.post("/buyer-intents", json=data, headers=ORIGIN).status_code == 422


def test_invalid_origin_refused(monkeypatch):
    setup(monkeypatch, FakeDatabase())
    with nullcontext(TestClient(app)) as client:
        assert client.post("/buyer-intents", json=make_payload(), headers={"Origin": "https://evil.test"}).status_code == 403


def test_no_false_success_on_database_failure(monkeypatch):
    setup(monkeypatch, FakeDatabase(fail=True))
    with nullcontext(TestClient(app)) as client:
        res = client.post("/buyer-intents", json=make_payload(), headers=ORIGIN)
    assert res.status_code == 503
    assert "private db message" not in res.text


def test_unrecognized_listing_is_rejected(monkeypatch):
    setup(monkeypatch, FakeDatabase())
    data = make_payload()
    data["listing_url"] = "https://some-unknown-vendor.example/offer"
    with nullcontext(TestClient(app)) as client:
        assert client.post("/buyer-intents", json=data, headers=ORIGIN).status_code == 422
