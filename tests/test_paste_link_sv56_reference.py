"""Census coverage means recognizing references, not extracting 56 inventories."""
from __future__ import annotations

from urllib.parse import urlsplit
import pytest
from fastapi.testclient import TestClient

from app.paste_link_56_reference import reference_for_url, reference_coverage, _registry
from app.paste_link_source_registry import source_for_url
from app.paste_link_staging import app


def test_exact_all_56_atlas_sources_recognized_without_fetch_or_storage():
    data, hosts = _registry()
    assert len(data["sources"]) == 56
    assert len(hosts) == 56
    seen = set()
    for entry in data["sources"]:
        outcome = reference_for_url(entry["homepage"])
        assert outcome is not None, entry["source_id"]
        assert outcome["source_id"] == entry["source_id"]
        assert outcome["source_name"] == entry["name"]
        assert outcome["within_original_56"] is True
        assert outcome["saved"] is False
        assert outcome["fetched"] is False
        assert outcome["vehicle_fields_verified"] is False
        seen.add(outcome["source_id"])
    assert len(seen) == 56


def test_reference_safety_rejects_untrusted_domain_credentials_and_ip():
    candidates = [
        "http://www.toyota.com.sv/autos",
        "https://127.0.0.1/vehicle",
        "https://localhost/",
        "https://192.168.1.1/",
        "https://www.toyota.com.sv:443/car",
        "https://user:pass@www.toyota.com.sv/car",
        "https://www.toyota.com.sv.evil.example/car",
        "https://evil.example/?next=www.toyota.com.sv",
        "https://[::1]/",
        "https://www.toyota.com.sv/car\nX-header: injected",
        "https://www.toyota.com.sv/" + "x" * 2200,
    ]
    for candidate in candidates:
        assert reference_for_url(candidate) is None, candidate


def test_catalog_or_blocked_sites_recognized_without_automatic_fetch():
    for url in (
        "https://www.toyota.com.sv/vehiculos/corolla",
        "https://www.encuentra24.com/el-salvador-es/autos-usados/test/123456789",
        "https://autosale.com.sv/catalogo.php#vehicle-145",
        "https://www.baccredomatic.com/es-sv/personas/catalogo-de-vehiculos#vehicle-95036",
        "https://finder.porsche.com/sv/es-SV/details/car-id",
    ):
        outcome = reference_for_url(url)
        assert outcome and outcome["saved"] is False and outcome["fetched"] is False
        assert outcome["vehicle_fields_verified"] is False
    # Recognition MUST NOT modify the exact approved routes of the fetcher.
    assert source_for_url("https://www.encuentra24.com/el-salvador-es/autos-usados/test/123456789") is None
    assert source_for_url("https://www.toyota.com.sv/vehiculos/corolla") is None


def test_one_additional_anuto_source_not_hidden_in_original_56():
    candidate = reference_for_url("https://sv.anuto.app/ad/any-synthetic-test")
    assert candidate and candidate["within_original_56"] is False
    cover = reference_coverage()
    assert cover["registered_sources"] == 56
    assert cover["recognized_reference_domains"] == 56
    assert cover["sample_verified_of_56"] == 10
    assert cover["trial_unverified_of_56"] == 3
    assert cover["other_not_automatically_verified"] == 43
    assert cover["additional_sample_verified_domains"] == 1
    assert cover["production_deploy_permitted"] is False
    assert cover["network_fetch"] is False
    assert cover["intake_enabled"] is False


def test_staging_endpoint_recognizes_safe_catalog_without_saving_or_fetching():
    import app.paste_link_staging as stage
    stage._limits.clear()
    client = TestClient(app)
    health = client.get("/api/coverage-56")
    assert health.status_code == 200
    assert health.json()["registered_sources"] == 56
    reply = client.post("/api/reference", json={"url": "https://www.toyota.com.sv/autos/corolla"})
    assert reply.status_code == 200
    data = reply.json()
    assert data["status"] == "recognized_unstored"
    assert data["source_id"] == "sv-toyota"
    assert data["saved"] is False and data["fetched"] is False
    assert "url" not in data and "buyer_contact" not in data
    assert reply.headers["cache-control"] == "no-store, max-age=0"
    unknown = client.post("/api/reference", json={"url": "https://not-a-source.example/car/123"})
    assert unknown.status_code == 400


def test_staging_ui_explains_reference_only_and_keeps_manual_fallback():
    from app.paste_link_staging import STAGING_PAGE
    assert '/api/reference' in STAGING_PAGE
    assert '/api/coverage-56' in STAGING_PAGE
    assert 'id="sv56-reference"' in STAGING_PAGE
    assert 'recognized_unstored' in STAGING_PAGE
    assert 'id="manual-helper"' in STAGING_PAGE
    assert "no se guardó" in STAGING_PAGE
