import json
import os
from types import SimpleNamespace

os.environ.setdefault("CACHE_DB", "/tmp/carly-handoff-cache.db")
os.environ.setdefault("TRUSTPLUS_DB", "/tmp/carly-handoff-trust.db")
os.environ.setdefault("CARLY_VISION_JIT_ENABLED", "0")

from app import main_v51, main_v50
from app import carly_v58_conversation_scope as scope
from app.atlas_refresh_orchestrator import _refresh_observed_existing
from app.enlaces_vehicle_evidence import vehicle_evidence


def _html(vehicle_id=24, status="Disponible"):
    car = {"id": vehicle_id, "brand_name": "MAZDA", "name": "CX-30 SELECT 2021",
           "year": 2021, "price": "122000.0", "discount_price": None,
           "odometer": 70288, "odometer_unit": "MI", "transmission_display": "Triptronic",
           "fuel_type_display": "Gasolina", "status_display": status,
           "thumbnail": {"image": "https://images.example.test/cx30.jpg"},
           "description": "Synthetic vehicle evidence"}
    stream = '29:' + json.dumps(["$", "component", None, {"car": car}]) + '\n'
    return '<script>self.__next_f.push(' + json.dumps([1, stream]) + ')</script>'


def test_enlaces_uses_requested_vehicle_facts_and_converts_miles():
    evidence = vehicle_evidence("https://www.enlacesautomotrices.com/menu/cars/24", _html())
    assert evidence["km"] == 113118
    assert evidence["transmission"] == "Automática"
    assert evidence["price_usd"] == 122000
    assert evidence["currency"] == "GTQ"
    assert evidence["model"] == "CX-30 SELECT"


def test_enlaces_rejects_other_vehicle_and_other_domain():
    assert vehicle_evidence("https://www.enlacesautomotrices.com/menu/cars/25", _html()) == {}
    assert vehicle_evidence("https://unrelated.example.test/menu/cars/24", _html()) == {}


def test_enlaces_unavailable_vehicle_does_not_pass_extraction():
    from app.atlas_manifest_runner import extract_listing
    out = extract_listing({"required_fields": ["title", "url"]},
                          "https://www.enlacesautomotrices.com/menu/cars/24", _html(status="Vendido"))
    assert out["_required_ok"] is False


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.updates = None
    def select(self, *args): return self
    def eq(self, field, value):
        self.filters.append((field, "eq", value)); return self
    def gte(self, field, value):
        self.filters.append((field, "gte", value)); return self
    def lte(self, field, value):
        self.filters.append((field, "lte", value)); return self
    def ilike(self, field, value):
        self.filters.append((field, "ilike", value)); return self
    def order(self, *args, **kwargs): return self
    def limit(self, *args): return self
    def contains(self, *args): return self
    def update(self, value): self.updates = value; return self
    def execute(self):
        rows = self.rows
        for field, op, value in self.filters:
            if op == "eq": rows = [r for r in rows if r.get(field) == value]
            elif op == "gte": rows = [r for r in rows if r.get(field, "") >= value]
            elif op == "lte": rows = [r for r in rows if r.get(field, 0) <= value]
            elif op == "ilike": rows = [r for r in rows if value.strip('%').lower() in str(r.get(field, '')).lower()]
        return SimpleNamespace(data=rows)


def test_brand_and_exact_queries_exclude_stale_shadow_and_other_markets(monkeypatch):
    base = {"make": "Mazda", "country": "gt", "status": "staging", "listing_state": "indexed",
            "is_addressable": True, "last_seen_at": "2026-10-04T00:00:00+00:00", "price_usd": 20000}
    rows = [dict(base, id=1), dict(base, id=2, last_seen_at="2026-09-12T00:00:00+00:00"),
            dict(base, id=3, status="atlas_shadow"), dict(base, id=4, country="sv")]
    monkeypatch.setattr(main_v50.legacy, "supabase", SimpleNamespace(table=lambda _: Query(rows)))
    monkeypatch.setattr(main_v50, "freshness_policy", lambda _: {"cutoff": "2026-10-03T00:00:00+00:00"})
    for constraints in ({"require_brand": "Mazda"}, {"exact": ("Mazda", "CX-5", "suv")}, {}):
        assert [r["id"] for r in scope._query_rows(constraints, "gt")] == [1]


def test_refresh_updates_proven_facts_without_changing_publication(monkeypatch):
    from app import atlas_refresh_orchestrator as refresh
    row = {"id": 1, "url": "https://example.test/car", "price_usd": 10000, "status": "staging"}
    monkeypatch.setattr(refresh, "_exact_staging_rows", lambda *args: [row])
    query = Query([row])
    client = SimpleNamespace(table=lambda _: query)
    assert _refresh_observed_existing(client, source_id="gt-enlacesautomotrices-com", manifest_version=2,
        observed_urls={row["url"]}, evidence_records={row["url"]: {
            "price_usd": 15993.0, "transmission": "Automática", "km": 113118,
            "status": "atlas_shadow", "is_addressable": False}}) == 1
    assert query.updates["km"] == 113118
    assert query.updates["transmission"] == "Automática"
    assert query.updates["monthly_est"] == round(15993 * 0.0238)
    assert "status" not in query.updates
    assert "is_addressable" not in query.updates
