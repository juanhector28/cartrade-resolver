"""Link-first intake contract: no scrapers, fail closed, explicit consent, durable receipt."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.link_first_intake import router

FAKE_SITE = "https://cartrade.live"
FACEBOOK = "https://www.facebook.com/marketplace/item/128374102938/?ref=share"
UNKNOWN = "https://unlisted-marketplace.example/vehicle/abc123"


class FakeDB:
    def __init__(self, fail=False):
        self.row = None
        self.fail = fail

    def table(self, name):
        assert name == "buyer_intents"
        return self

    def upsert(self, row, on_conflict, ignore_duplicates):
        assert on_conflict == "request_id"
        assert ignore_duplicates is True
        self.row = row
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("Sensitive database error")
        return SimpleNamespace(data=[self.row])


def build(monkeypatch, *, enabled=True, abuse=True, db=None):
    app = FastAPI()
    app.include_router(router)
    app.state.link_first_db = db if db is not None else FakeDB()

    async def verify(_request):
        return abuse
    app.state.link_first_abuse_verifier = verify

    monkeypatch.setenv("LINK_FIRST_STORE_TABLE", "buyer_intents")
    monkeypatch.setenv("LINK_FIRST_ALLOWED_ORIGINS", FAKE_SITE)
    if enabled:
        monkeypatch.setenv("LINK_FIRST_INTAKE_ENABLED", "1")
    else:
        monkeypatch.delenv("LINK_FIRST_INTAKE_ENABLED", raising=False)
    return TestClient(app)


def payload(url=FACEBOOK):
    return {
        "request_id": str(uuid4()),
        "listing_url": url,
        "buyer_contact": "+503 7000-0000",
        "contact_channel": "whatsapp",
        "country": "sv",
        "source": "paste_link",
        "consent_to_contact": True,
    }


def test_off_by_default(monkeypatch):
    client = build(monkeypatch, enabled=False)
    assert client.post("/buyer-intents", json=payload(), headers={"origin": FAKE_SITE}).status_code == 503


def test_facebook_marketplace_link_without_title_or_price(monkeypatch):
    db = FakeDB()
    client = build(monkeypatch, db=db)
    data = payload()
    response = client.post("/buyer-intents", json=data, headers={"origin": FAKE_SITE})
    assert response.status_code == 201
    assert response.json() == {"status": "received", "request_id": data["request_id"]}
    assert response.headers["cache-control"] == "no-store"
    assert db.row == {
        "request_id": data["request_id"],
        "listing_url": data["listing_url"],
        "buyer_contact": "50370000000",
        "contact_channel": "whatsapp",
        "country": "sv",
        "source": "paste_link",
        "car_name": "Vehículo pendiente de identificar",
        "price_usd": None,
        "consent_to_contact": True,
        "status": "received",
    }


def test_unknown_domain_allowed_without_site_integration(monkeypatch):
    db = FakeDB()
    client = build(monkeypatch, db=db)
    result = client.post("/buyer-intents", json=payload(UNKNOWN), headers={"origin": FAKE_SITE})
    assert result.status_code == 201
    assert db.row["listing_url"] == UNKNOWN


def test_consent_required(monkeypatch):
    client = build(monkeypatch)
    data = payload()
    data["consent_to_contact"] = False
    assert client.post("/buyer-intents", json=data, headers={"origin": FAKE_SITE}).status_code == 422


def test_reject_untrusted_origin_and_nonpublic_urls(monkeypatch):
    client = build(monkeypatch)
    assert client.post("/buyer-intents", json=payload(), headers={"origin": "https://evil.example"}).status_code == 403
    for url in (
        "http://example.com/offer",
        "https://localhost/car",
        "https://127.0.0.1/car",
        "https://10.0.0.4/private",
        "https://[::1]/car",
        "https://user:pass@example.com/car",
        "https://internal.local/car",
    ):
        assert client.post("/buyer-intents", json=payload(url), headers={"origin": FAKE_SITE}).status_code == 422, url


def test_fail_closed_without_real_abuse_verifier(monkeypatch):
    client = build(monkeypatch, abuse=False)
    assert client.post("/buyer-intents", json=payload(), headers={"origin": FAKE_SITE}).status_code == 429
    app = FastAPI()
    app.include_router(router)
    app.state.link_first_db = FakeDB()
    monkeypatch.setenv("LINK_FIRST_INTAKE_ENABLED", "1")
    monkeypatch.setenv("LINK_FIRST_STORE_TABLE", "buyer_intents")
    assert TestClient(app).post("/buyer-intents", json=payload(), headers={"origin": FAKE_SITE}).status_code == 503


def test_storage_failure_never_acknowledged(monkeypatch):
    client = build(monkeypatch, db=FakeDB(fail=True))
    result = client.post("/buyer-intents", json=payload(), headers={"origin": FAKE_SITE})
    assert result.status_code == 503
    assert "Sensitive database error" not in result.text
