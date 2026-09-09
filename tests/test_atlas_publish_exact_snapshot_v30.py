from __future__ import annotations

from copy import deepcopy

from app.atlas_publish_api import AtlasPublishRequest, publish_source


SOURCE_ID = "gt-resolver-publisher-fixture"
VERSION = 1
KEY = f"publish:{SOURCE_ID}:{VERSION}"


def _contains(obj, subset):
    if isinstance(subset, dict):
        if not isinstance(obj, dict):
            return False
        return all(k in obj and _contains(obj[k], v) for k, v in subset.items())
    return obj == subset


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store):
        self.store = store
        self.filters = []
        self.limit_n = None
        self.update_payload = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def contains(self, key, value):
        self.filters.append(("contains", key, value))
        return self

    def limit(self, n):
        self.limit_n = int(n)
        return self

    def update(self, payload):
        self.update_payload = dict(payload)
        return self

    def _match(self, row):
        for kind, key, value in self.filters:
            if kind == "eq" and row.get(key) != value:
                return False
            if kind == "contains" and not _contains(row.get(key), value):
                return False
        return True

    def execute(self):
        matched = [row for row in self.store if self._match(row)]
        if self.limit_n is not None:
            matched = matched[: self.limit_n]
        if self.update_payload is None:
            return _Result([deepcopy(row) for row in matched])

        out = []
        for row in matched:
            row.update(deepcopy(self.update_payload))
            out.append(deepcopy(row))
        return _Result(out)


class _Supabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "scraped_listings"
        return _Query(self.rows)


def _row(i: int, *, valid: bool = True):
    return {
        "id": i + 1,
        "url": f"https://dealer.test/vehicle/{i}",
        "status": "atlas_shadow",
        "source": "atlas:dealer.test",
        "raw_payload": {
            "atlas": {
                "source_id": SOURCE_ID,
                "manifest_version": VERSION,
            }
        },
        "is_addressable": True,
        "updated_at": f"2026-09-09T20:00:{i:02d}+00:00",
        "make": "Toyota" if valid else "Vehículos Relacionados",
        "model": "Corolla",
        "year": 2024,
        "price_usd": 20000 + i,
    }


def _body(*, dry_run: bool, expected_snapshot_hash: str | None = None):
    return AtlasPublishRequest(
        source_id=SOURCE_ID,
        manifest_version=VERSION,
        idempotency_key=KEY,
        min_listings=10,
        dry_run=dry_run,
        expected_snapshot_hash=expected_snapshot_hash,
    )


def test_one_canonical_invalid_of_twenty_is_excluded_per_listing(monkeypatch):
    monkeypatch.setenv("ATLAS_PUBLISH_SEMANTIC_ASSERT_MAX_ROWS", "100")
    rows = [_row(i) for i in range(19)] + [_row(19, valid=False)]
    supabase = _Supabase(rows)

    preview = publish_source(supabase, _body(dry_run=True))
    assert preview["result"] == "ready"
    assert preview["shadow_candidate_count"] == 20
    assert preview["valid_shadow_candidate_count"] == 19
    assert preview["canonical_invalid_shadow_count"] == 1
    assert preview["canonical_invalid_shadow_urls"] == ["https://dealer.test/vehicle/19"]
    assert preview["semantic_assertion_complete"] is True
    assert preview["semantic_assertion_row_count"] == 19
    assert len(preview["candidate_snapshot_hash"]) == 64

    published = publish_source(
        supabase,
        _body(
            dry_run=False,
            expected_snapshot_hash=preview["candidate_snapshot_hash"],
        ),
    )
    assert published["result"] == "published"
    assert published["promoted_count"] == 19
    assert published["final_addressable_count"] == 19

    valid_rows = rows[:19]
    invalid_row = rows[19]
    assert all(row["status"] == "staging" for row in valid_rows)
    assert invalid_row["status"] == "atlas_shadow"


def test_snapshot_change_rejects_before_any_publish_mutation(monkeypatch):
    monkeypatch.setenv("ATLAS_PUBLISH_SEMANTIC_ASSERT_MAX_ROWS", "100")
    rows = [_row(i) for i in range(20)]
    supabase = _Supabase(rows)

    preview = publish_source(supabase, _body(dry_run=True))
    assert preview["result"] == "ready"
    frozen_hash = preview["candidate_snapshot_hash"]

    # Simulate a database snapshot change after semantic preflight.
    rows[7]["model"] = "Camry"

    result = publish_source(
        supabase,
        _body(dry_run=False, expected_snapshot_hash=frozen_hash),
    )
    assert result["result"] == "rejected_precondition"
    assert result["reason"] == "candidate_snapshot_changed"
    assert result["expected_snapshot_hash"] == frozen_hash
    assert result["actual_snapshot_hash"] != frozen_hash
    assert result["promoted_count"] == 0
    assert all(row["status"] == "atlas_shadow" for row in rows)
