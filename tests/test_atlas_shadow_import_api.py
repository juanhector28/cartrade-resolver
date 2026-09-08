import pytest
from fastapi import HTTPException

from app.atlas_publish_api import (
    AtlasShadowImportRequest,
    _require_publish_token,
    import_shadow_items,
)


class Response:
    def __init__(self, data):
        self.data = data
        self.count = len(data)


def _contains(row, value):
    atlas = ((row.get("raw_payload") or {}).get("atlas") or {})
    expected = ((value or {}).get("atlas") or {})
    return all(atlas.get(k) == v for k, v in expected.items())


class Query:
    def __init__(self, db):
        self.db = db
        self.filters = []
        self.limit_n = None
        self.selected = None
        self.mode = "select"
        self.payload = None

    def select(self, columns, count=None):
        self.selected = columns.split(",") if columns != "*" else None
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def contains(self, key, value):
        assert key == "raw_payload"
        self.filters.append(("contains", key, value))
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def update(self, payload):
        self.mode = "update"
        self.payload = dict(payload)
        return self

    def insert(self, payload):
        self.mode = "insert"
        self.payload = dict(payload)
        return self

    def _matches(self, row):
        for op, key, value in self.filters:
            if op == "eq" and row.get(key) != value:
                return False
            if op == "contains" and not _contains(row, value):
                return False
        return True

    def execute(self):
        if self.mode == "insert":
            url = self.payload.get("url")
            if any(row.get("url") == url for row in self.db.rows):
                raise RuntimeError("duplicate url")
            row = dict(self.payload)
            row.setdefault("id", self.db.next_id)
            self.db.next_id += 1
            self.db.rows.append(row)
            return Response([dict(row)])

        matched = [row for row in self.db.rows if self._matches(row)]
        if self.limit_n is not None:
            matched = matched[: self.limit_n]

        if self.mode == "update":
            out = []
            for row in matched:
                row.update(self.payload)
                out.append(dict(row))
            return Response(out)

        rows = [dict(row) for row in matched]
        if self.selected is not None:
            rows = [{k: row.get(k) for k in self.selected if k in row} for row in rows]
        return Response(rows)


class Supabase:
    def __init__(self, rows=None):
        self.rows = [dict(row) for row in (rows or [])]
        self.next_id = max([int(row.get("id") or 0) for row in self.rows] + [0]) + 1

    def table(self, name):
        assert name == "scraped_listings"
        return Query(self)


def item(i, *, valid=True):
    row = {
        "url": f"https://dealer.gt/autos/toyota-corolla-202{i % 10}-{10000+i}",
        "title": f"Toyota Corolla 202{i % 10}",
        "make": "Toyota",
        "model": "Corolla",
        "year": 2020 + (i % 6),
        "price": 15000 + i,
        "currency": "USD",
        "mileage": 20000 + i,
        "photos": [f"https://img.gt/{i}.jpg"],
        "_atlas_extractor": "structured_v49",
    }
    if not valid:
        row["price"] = None
    return row


def body(items, min_listings=10, manifest_version=7):
    return AtlasShadowImportRequest(
        source_id="gt-autogogt-com",
        manifest_version=manifest_version,
        country="GT",
        domain="autogogt.com",
        min_listings=min_listings,
        items=items,
    )


def test_import_persists_valid_structured_rows_as_exact_shadow():
    db = Supabase()
    result = import_shadow_items(db, body([item(i) for i in range(10)]))

    assert result["result"] == "imported"
    assert result["saved_shadow"] == 10
    assert result["final_valid_shadow_count"] == 10
    assert result["addressable"] is False
    assert len(db.rows) == 10
    assert all(row["status"] == "atlas_shadow" for row in db.rows)
    assert all(row["price_usd"] > 0 for row in db.rows)
    assert all(
        row["raw_payload"]["atlas"]["source_id"] == "gt-autogogt-com"
        and row["raw_payload"]["atlas"]["manifest_version"] == 7
        for row in db.rows
    )


def test_import_never_overwrites_existing_production_owner():
    sentinel = {
        "id": 1,
        "url": item(0)["url"],
        "status": "staging",
        "source": "manual-source",
        "make": "Sentinel",
        "model": "Protected",
        "year": 2024,
        "price_usd": 9999,
        "is_addressable": True,
        "raw_payload": {"manual": True},
    }
    db = Supabase([sentinel])
    result = import_shadow_items(db, body([item(i) for i in range(10)]))

    assert result["result"] == "insufficient_after_collisions"
    assert result["protected_collision_count"] == 1
    protected = next(row for row in db.rows if row["id"] == 1)
    assert protected["source"] == "manual-source"
    assert protected["make"] == "Sentinel"
    assert protected["status"] == "staging"


def test_same_source_shadow_can_refresh_to_current_manifest():
    old = {
        "id": 1,
        "url": item(0)["url"],
        "status": "atlas_shadow",
        "source": "atlas:autogogt.com",
        "make": "Toyota",
        "model": "Corolla",
        "year": 2020,
        "price_usd": 12000,
        "is_addressable": False,
        "raw_payload": {"atlas": {"source_id": "gt-autogogt-com", "manifest_version": 6}},
    }
    db = Supabase([old])
    result = import_shadow_items(db, body([item(i) for i in range(10)], manifest_version=7))

    assert result["result"] == "imported"
    assert result["refreshed_shadow"] == 1
    refreshed = next(row for row in db.rows if row["id"] == 1)
    assert refreshed["raw_payload"]["atlas"]["manifest_version"] == 7
    assert refreshed["status"] == "atlas_shadow"


def test_import_rejects_bad_source_level_coverage_before_writing():
    db = Supabase()
    rows = [item(i, valid=i >= 3) for i in range(10)]
    result = import_shadow_items(db, body(rows, min_listings=5))

    assert result["result"] == "rejected_precondition"
    assert result["reason"] == "core_listing_coverage_below_80"
    assert result["valid_count"] == 7
    assert db.rows == []


def test_import_auth_is_same_fail_closed_publish_token(monkeypatch):
    for name in ("ATLAS_PUBLISH_TOKEN", "ATLAS_BRIDGE_TOKEN", "CRON_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(HTTPException) as missing:
        _require_publish_token("anything")
    assert missing.value.status_code == 503

    monkeypatch.setenv("ATLAS_BRIDGE_TOKEN", "expected")
    with pytest.raises(HTTPException) as invalid:
        _require_publish_token("wrong")
    assert invalid.value.status_code == 401
    _require_publish_token("expected")
