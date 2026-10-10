from datetime import datetime, timezone
from app.source_access_policy import may_ingest

AT = datetime(2026, 10, 10, tzinfo=timezone.utc)

def valid_grant():
    return {
        "status": "approved", "permission": "commercial_inventory_ingestion",
        "agreement_reference": "test-agreement-001",
        "redisplay_permitted": True, "price_collection_permitted": True,
        "expires_at": "2027-10-10T00:00:00Z",
    }

def test_encuentra24_rejected_without_written_grant():
    assert may_ingest("encuentra24", None, at=AT) == (False, "written_authorization_missing")

def test_unknown_source_requires_policy_review():
    assert may_ingest("new-marketplace", valid_grant(), at=AT)[0] is False

def test_valid_written_authorization():
    assert may_ingest("encuentra24", valid_grant(), at=AT) == (True, "authorized")

def test_expired_authorization_rejected():
    grant = valid_grant()
    grant["expires_at"] = "2026-01-01T00:00:00Z"
    assert may_ingest("encuentra24", grant, at=AT)[0] is False

def test_no_photo_or_price_rights_rejected():
    grant = valid_grant()
    grant["redisplay_permitted"] = False
    assert may_ingest("encuentra24", grant, at=AT)[0] is False
