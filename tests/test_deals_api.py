"""Regression checks for Deals auth boundary (dependency mocked, no production calls)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.deals_api import router, _client

class FakeQuery:
    def __init__(self, rows):
        self.db = rows
    def select(self, *_): return self
    def order(self, *_args, **_kwargs): return self
    def limit(self, *_): return self
    def eq(self, name, value):
        self.db.rows = [r for r in self.db.rows if r.get(name) == value]
        return self
    def insert(self, row):
        self.db.rows.append(dict(row, id="00000000-0000-0000-0000-000000000001"))
        return self
    def execute(self):
        class Reply: pass
        r = Reply()
        r.data = self.db.rows
        return r

class FakeDB:
    def __init__(self): self.rows=[]
    def table(self, name):
        assert name == "ct_deals"
        return FakeQuery(self)

app = FastAPI()
app.include_router(router)
client = TestClient(app)

def test_auth_required():
    assert client.get("/api/deals").status_code == 401
    assert client.post("/api/deals", json={"market":"sv","actor_role":"broker"}).status_code == 401

def test_bad_payload_rejected_before_write():
    app.dependency_overrides[_client] = lambda: (FakeDB(), "00000000-0000-0000-0000-000000000002")
    try:
        assert client.post("/api/deals",json={"market":"invalid","actor_role":"broker"}).status_code == 422
        assert client.post("/api/deals",json={"market":"sv","actor_role":"admin"}).status_code == 422
        assert client.post("/api/deals",json={"market":"sv","actor_role":"buyer","asking_price_usd":-1}).status_code == 422
    finally:
        app.dependency_overrides.clear()

def test_draft_created_without_client_status():
    app.dependency_overrides[_client] = lambda: (FakeDB(), "00000000-0000-0000-0000-000000000002")
    try:
        r=client.post("/api/deals",json={"market":"sv","actor_role":"broker","status":"closed"})
        assert r.status_code == 201
        assert r.json()["deal"]["status"] == "discovery"
    finally:
        app.dependency_overrides.clear()

def test_created_deal_is_retrievable_in_new_request():
    db = FakeDB()
    app.dependency_overrides[_client] = lambda: (db, "00000000-0000-0000-0000-000000000002")
    try:
        created = client.post("/api/deals",json={"market":"gt","actor_role":"broker","vehicle_title":"Hilux"})
        assert created.status_code == 201
        deal_id = created.json()["deal"]["id"]
        retrieved = client.get("/api/deals/"+deal_id)
        assert retrieved.status_code == 200
        assert retrieved.json()["deal"]["vehicle_title"] == "Hilux"
    finally:
        app.dependency_overrides.clear()
