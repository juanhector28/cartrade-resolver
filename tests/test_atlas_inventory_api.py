import os

import pytest
from fastapi import HTTPException

from atlas_inventory_api import _require_read_token, inventory_summary, query_inventory


class Response:
    def __init__(self, data, count=None):
        self.data = data
        self.count = len(data) if count is None else count


class Query:
    def __init__(self, rows):
        self.rows = list(rows)
        self.filters = []
        self.selected = None
        self.start = 0
        self.end = None

    def select(self, columns, count=None):
        self.selected = columns.split(",")
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def contains(self, key, value):
        self.filters.append(("contains", key, value))
        return self

    def ilike(self, key, value):
        self.filters.append(("ilike", key, value.strip("%").lower()))
        return self

    def gte(self, key, value):
        self.filters.append(("gte", key, value))
        return self

    def lte(self, key, value):
        self.filters.append(("lte", key, value))
        return self

    def order(self, *args, **kwargs):
        return self

    def range(self, start, end):
        self.start, self.end = start, end
        return self

    def limit(self, count):
        self.start, self.end = 0, count - 1
        return self

    def execute(self):
        rows = list(self.rows)
        for op, key, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if r.get(key) == value]
            elif op == "ilike":
                rows = [r for r in rows if value in str(r.get(key) or "").lower()]
            elif op == "gte":
                rows = [r for r in rows if r.get(key) is not None and r[key] >= value]
            elif op == "lte":
                rows = [r for r in rows if r.get(key) is not None and r[key] <= value]
            elif op == "contains":
                source_id = value["atlas"]["source_id"]
                rows = [r for r in rows if r.get("raw_payload", {}).get("atlas", {}).get("source_id") == source_id]
        total = len(rows)
        if self.end is not None:
            rows = rows[self.start:self.end + 1]
        if self.selected:
            rows = [{k: r.get(k) for k in self.selected if k in r} for r in rows]
        return Response(rows, total)


class Supabase:
    def __init__(self, rows):
        self.rows = rows
        self.last_query = None

    def table(self, name):
        assert name == "scraped_listings"
        self.last_query = Query(self.rows)
        return self.last_query


ROWS = [
    {"id": 1, "country": "gt", "status": "atlas_shadow", "make": "Toyota", "model": "RAV4", "year": 2021,
     "price_usd": 20000, "updated_at": "2026-08-23T10:00:00Z", "source": "atlas:movilauto.com",
     "raw_payload": {"secret": "must-not-leak", "atlas": {"source_id": "gt-movilauto-com"}}},
    {"id": 2, "country": "cr", "status": "atlas_shadow", "make": "Honda", "model": "CR-V", "year": 2020,
     "price_usd": 18000, "updated_at": "2026-08-23T09:00:00Z", "source": "atlas:encuentra24.com",
     "raw_payload": {"atlas": {"source_id": "cr-encuentra24-com"}}},
    {"id": 3, "country": "gt", "status": "staging", "make": "Toyota", "model": "Hilux", "year": 2022,
     "price_usd": 25000, "updated_at": "2026-08-23T08:00:00Z", "source": "encuentra24"},
]


def test_inventory_is_shadow_only_filtered_and_safe():
    db = Supabase(ROWS)
    result = query_inventory(db, country="GT", make="toy", min_year=2020, max_price=22000)
    assert result["total"] == 1
    assert result["items"][0]["id"] == 1
    assert "raw_payload" not in result["items"][0]
    assert ("eq", "status", "atlas_shadow") in db.last_query.filters


def test_source_id_filter_uses_private_metadata_without_returning_it():
    result = query_inventory(Supabase(ROWS), source_id="cr-encuentra24-com")
    assert [row["id"] for row in result["items"]] == [2]
    assert all("raw_payload" not in row for row in result["items"])


def test_summary_excludes_production_rows():
    result = inventory_summary(Supabase(ROWS))
    assert result["total"] == 2
    assert result["by_country"] == {"CR": 1, "GT": 1}


def test_auth_fails_closed(monkeypatch):
    for name in ("ATLAS_INVENTORY_READ_TOKEN", "ATLAS_BRIDGE_TOKEN", "CRON_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(HTTPException) as missing:
        _require_read_token("anything")
    assert missing.value.status_code == 503

    monkeypatch.setenv("ATLAS_BRIDGE_TOKEN", "expected")
    with pytest.raises(HTTPException) as invalid:
        _require_read_token("wrong")
    assert invalid.value.status_code == 401
    _require_read_token("expected")


def test_unsupported_country_rejected():
    with pytest.raises(HTTPException) as invalid:
        query_inventory(Supabase(ROWS), country="us")
    assert invalid.value.status_code == 422
