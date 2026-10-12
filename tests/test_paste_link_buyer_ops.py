"""Buyer request inbox: Supabase Auth OTP, individual staff membership and PII gating."""
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app import rate_limit, buyer_ops
from app.main import app

USER_ID = str(uuid4())
EMAIL = "operator@cartrade.example"
TOKEN = "verified_supabase_access_token_" + "a" * 40
ID = str(uuid4())
ROW = {
    "request_id": ID, "created_at": "2026-10-12T13:00:00+00:00",
    "buyer_contact": "70000000", "contact_channel": "whatsapp",
    "listing_url": "https://www.julajups.sv/anuncio/toyota-4-runner-trd-2019-4x4-N3tSneYO52",
    "car_name": "Toyota 4Runner TRD 2019", "price_usd": 27500,
    "country": "sv", "status": "received", "consent_recorded_at": "2026-10-12T13:00:00+00:00",
}


class FakeAuth:
    def __init__(self):
        self.sent = []
        self.code = "123456"

    def get_user(self, token):
        if token != TOKEN:
            raise RuntimeError("Invalid token")
        return SimpleNamespace(user=SimpleNamespace(id=USER_ID, email=EMAIL))

    def sign_in_with_otp(self, params):
        self.sent.append(params)

    def verify_otp(self, params):
        if params.get("email") != EMAIL or params.get("token") != self.code:
            raise RuntimeError("OTP invalid")
        return SimpleNamespace(
            user=SimpleNamespace(id=USER_ID, email=EMAIL),
            session=SimpleNamespace(access_token=TOKEN),
        )


class FakeQuery:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.mode = "select"
        self.where = {}

    def select(self, columns):
        self.db.columns = columns
        return self

    def order(self, field, desc=False):
        self.db.sorted_by = field
        return self

    def range(self, start, end):
        self.db.range_requested = (start, end)
        return self

    def limit(self, n):
        return self

    def update(self, fields):
        self.mode = "update"
        self.db.fields = fields
        return self

    def eq(self, name, value):
        self.where[name] = value
        return self

    def execute(self):
        if self.db.fail:
            raise RuntimeError("private db error with sensitive content")
        if self.table == "buyer_ops_staff":
            if not self.db.staff_active:
                return SimpleNamespace(data=[])
            if self.where.get("user_id", USER_ID) != USER_ID:
                return SimpleNamespace(data=[])
            if self.where.get("email", EMAIL) != EMAIL:
                return SimpleNamespace(data=[])
            if self.where.get("active", True) is not True:
                return SimpleNamespace(data=[])
            return SimpleNamespace(data=[{
                "user_id": USER_ID, "role": "operator",
                "active": True, "email": EMAIL
            }])
        if self.table != "buyer_intents":
            raise AssertionError("Unexpected table: " + self.table)
        if self.mode == "update":
            if self.where.get("request_id") != ID:
                return SimpleNamespace(data=[])
            self.db.row["status"] = self.db.fields["status"]
        return SimpleNamespace(data=[self.db.row.copy()])


class FakeDatabase:
    def __init__(self, fail=False, staff_active=True):
        self.fail = fail
        self.staff_active = staff_active
        self.row = ROW.copy()
        self.table_calls = []

    def table(self, name):
        self.table_calls.append(name)
        return FakeQuery(self, name)


def setup(monkeypatch, db=None):
    auth = FakeAuth()
    database = db or FakeDatabase()
    monkeypatch.setenv("BUYER_OPS_ENABLED", "1")
    monkeypatch.setenv("BUYER_INTENTS_TABLE", "buyer_intents")
    monkeypatch.setenv("BUYER_OPS_STAFF_TABLE", "buyer_ops_staff")
    monkeypatch.setattr(app.state, "buyer_intents_db", database, raising=False)
    monkeypatch.setattr(buyer_ops, "_auth_client", lambda: SimpleNamespace(auth=auth))
    monkeypatch.setattr(rate_limit, "check", lambda key: (True, 10))
    return database, auth


def client():
    return TestClient(app)


def headers(token=TOKEN):
    return {"Authorization": "Bearer " + token}


def test_inbox_feature_off(monkeypatch):
    monkeypatch.delenv("BUYER_OPS_ENABLED", raising=False)
    assert client().get("/ops/api/solicitudes").status_code == 404
    assert client().get("/ops/solicitudes").status_code == 404
    assert client().post("/ops/auth/start", json={"email": EMAIL}).status_code == 404


def test_inbox_misconfigured_database_fails_closed(monkeypatch):
    setup(monkeypatch)
    monkeypatch.delenv("BUYER_INTENTS_TABLE")
    assert client().get("/ops/api/solicitudes", headers=headers()).status_code == 503


def test_operator_must_have_verified_jwt(monkeypatch):
    setup(monkeypatch)
    for token in ("", "x" * 42, "abc" * 20):
        response = client().get("/ops/api/solicitudes", headers=headers(token))
        assert response.status_code == 401
        assert "buyer_contact" not in response.text


def test_verified_user_without_active_staff_membership_denied(monkeypatch):
    setup(monkeypatch, FakeDatabase(staff_active=False))
    assert client().get("/ops/api/solicitudes", headers=headers()).status_code == 403


def test_operator_otp_flow(monkeypatch):
    _, auth = setup(monkeypatch)
    response = client().post("/ops/auth/start", json={"email": EMAIL.upper()})
    assert response.status_code == 202
    assert response.headers["cache-control"] == "no-store"
    assert auth.sent == [{
        "email": EMAIL, "options": {"should_create_user": False}
    }]
    verify = client().post("/ops/auth/verify", json={"email": EMAIL, "code": "123456"})
    assert verify.status_code == 200
    assert verify.headers["cache-control"] == "no-store"
    assert verify.json()["access_token"] == TOKEN
    failed = client().post("/ops/auth/verify", json={"email": EMAIL, "code": "000000"})
    assert failed.status_code == 401


def test_unauthorized_email_never_receives_otp(monkeypatch):
    _, auth = setup(monkeypatch, FakeDatabase(staff_active=False))
    assert client().post("/ops/auth/start", json={"email": EMAIL}).status_code == 202
    assert not auth.sent


def test_private_page_exposes_no_customer_data_or_browser_storage(monkeypatch):
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
    assert 'id="email"' in response.text
    assert 'id="verify-form"' in response.text


def test_authorized_operator_lists_and_updates_request(monkeypatch):
    db, _ = setup(monkeypatch)
    r = client().get("/ops/api/solicitudes?limit=20&offset=0", headers=headers())
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.json()["items"][0]["buyer_contact"] == ROW["buyer_contact"]
    assert db.range_requested == (0, 19)
    assert "buyer_ops_staff" in db.table_calls and "buyer_intents" in db.table_calls

    updated = client().patch(
        "/ops/api/solicitudes/" + ID,
        json={"status": "in_review"}, headers=headers(),
    )
    assert updated.status_code == 200
    assert updated.json() == {"request_id": ID, "status": "in_review"}
    assert "buyer_contact" not in updated.text
    assert db.row["status"] == "in_review"


def test_reject_invalid_status_and_pagination(monkeypatch):
    setup(monkeypatch)
    assert client().patch(
        "/ops/api/solicitudes/" + ID,
        json={"status": "approved_financing"}, headers=headers()
    ).status_code == 422
    assert client().get("/ops/api/solicitudes?limit=200", headers=headers()).status_code == 422


def test_db_error_details_not_exposed(monkeypatch):
    setup(monkeypatch, FakeDatabase(fail=True))
    r = client().get("/ops/api/solicitudes", headers=headers())
    assert r.status_code in (401, 503)
    assert "private db error" not in r.text


def test_unknown_request_cannot_be_changed(monkeypatch):
    setup(monkeypatch)
    r = client().patch(
        "/ops/api/solicitudes/" + str(uuid4()),
        json={"status": "closed"}, headers=headers(),
    )
    assert r.status_code == 404
