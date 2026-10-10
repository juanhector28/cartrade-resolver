from datetime import datetime, timezone, timedelta
from app.listing_evidence_contract import current_asking_price

URL = "https://www.encuentra24.com/el-salvador-es/autos-usados/jeep-gladiator-2023/32882910"
NOW = datetime(2026, 10, 10, 20, 0, tzinfo=timezone.utc)

def evidence(**overrides):
    data = {"url": URL, "source_kind": "live_direct", "access_status": "ok",
            "captured_at": NOW.isoformat(), "price": 38000, "currency": "USD"}
    return dict(data, **overrides)

def test_live_current_jeep_price():
    result = current_asking_price(URL, evidence(), now=NOW)
    assert result["value"] == 38000 and result["verified"]

def test_historical_45000_does_not_override_current_38000():
    assert current_asking_price(URL, evidence(source_kind="historical", price=45000), now=NOW)["value"] is None

def test_blocked_browser_is_not_live_evidence():
    assert current_asking_price(URL, evidence(access_status="forbidden"), now=NOW)["reason"] == "source_not_accessible"

def test_stale_capture_rejected():
    assert current_asking_price(URL, evidence(captured_at=(NOW-timedelta(days=3)).isoformat()), now=NOW)["value"] is None

def test_other_listing_rejected():
    other = URL.replace("32882910", "32882911")
    assert current_asking_price(URL, evidence(url=other), now=NOW)["reason"] == "listing_identity_mismatch"

def test_price_without_timestamp_rejected():
    assert current_asking_price(URL, evidence(captured_at=None), now=NOW)["value"] is None

def test_authorized_feed_is_allowed():
    assert current_asking_price(URL, evidence(source_kind="live_authorized_feed"), now=NOW)["value"] == 38000
