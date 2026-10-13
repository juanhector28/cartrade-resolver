"""Offline release readiness checks: 11 pilot candidates != production clearance."""
import copy

from fastapi.testclient import TestClient
from app import paste_link_readiness as ledger
from app import paste_link_staging as staging

def test_real_qa_receipts_gate_eleven_sources_and_thirty_three_vehicles():
    data = ledger.get_readiness()
    assert data["environment"] == "staging"
    assert data["pilot_candidates"] == 11
    assert data["tested_domains"] == 11
    assert data["core_field_samples_verified"] == 33
    assert data["enabled_trial_domains"] == 14
    assert data["production_approved_domains"] == []
    assert data["production_deploy_permitted"] is False
    assert data["evidence_issues"] == []
    assert len({s["domain"] for s in data["sources"]}) == 11
    assert all(s["state"] == "pilot_candidate" for s in data["sources"])
    assert all(s["distinct_vehicle_urls"] == 3 for s in data["sources"])
    assert all(s["photos_loaded_in_browser_samples"] >= 1 for s in data["sources"])
    assert all(s["production_enabled"] is False for s in data["sources"])
    assert all(not c["approved"] for c in data["production_release_gates"].values())
    stages = {s["domain"]: s for s in data["other_registered_domains"]}
    assert stages["easycar.com.sv"]["stage"] == "javascript_required"
    assert stages["eurosportautos.com"]["stage"] == "access_review"
    assert stages["crediq.com"]["stage"] == "access_review"
    assert stages["encuentra24.com"]["enabled_for_manual_trial"] is False


def test_coverage_api_has_no_side_effects_and_does_not_publish_vehicle_urls():
    with TestClient(staging.app) as client:
        response = client.get("/api/coverage")
        assert response.status_code == 200
        payload = response.json()
        html = client.get("/").text
    assert payload["pilot_candidates"] == 11
    assert payload["core_field_samples_verified"] == 33
    assert payload["production_deploy_permitted"] is False
    assert "vehicle_urls" not in payload
    assert "anuncios/" not in response.text
    assert 'id="coverage"' in html
    assert 'fetch("/api/coverage")' in html


def test_release_controls_never_unlock_from_green_qa_alone(monkeypatch):
    actual_read = ledger._read
    control_data = copy.deepcopy(actual_read(ledger.CONTROLS))
    control_data["production_deploy_permitted"] = True
    control_data["approved_production_domains"] = ["carroselsalvador.com"]

    def fake_read(path):
        return control_data if path == ledger.CONTROLS else actual_read(path)

    monkeypatch.setattr(ledger, "_read", fake_read)
    status = ledger.get_readiness()
    assert status["pilot_candidates"] == 11
    assert status["production_deploy_permitted"] is False

    # Evidence-less checkboxes don't count as review, even with approved=True.
    for item in control_data["release_gates"].values():
        item["approved"] = True
        item["evidence"] = None
    status = ledger.get_readiness()
    assert status["production_deploy_permitted"] is False


def test_missing_or_duplicate_qa_receipts_fail_closed(monkeypatch):
    read = ledger._read
    matrix = copy.deepcopy(read(ledger.MATRIX))
    matrix["domains"][0]["cases"][2]["status"] = "pending"
    matrix["domains"][1]["cases"][1]["url"] = matrix["domains"][0]["cases"][1]["url"]

    def altered(path):
        return matrix if path == ledger.MATRIX else read(path)

    monkeypatch.setattr(ledger, "_read", altered)
    result = ledger.get_readiness()
    assert result["pilot_candidates"] < 11
    assert result["evidence_issues"]
    assert result["production_deploy_permitted"] is False


def test_runtime_disablelist_is_strictly_disable_only(monkeypatch):
    from app.paste_link_source_registry import source_for_url
    good = "https://www.carroselsalvador.com/anuncios/kia-sportage-2006/"
    another = "https://www.julajups.sv/anuncio/subaru-impreza-rs-2006-awd-pxODLWUM9S"
    candidate = "https://autosale.com.sv/catalogo.php#vehicle-145"
    assert source_for_url(good)
    assert source_for_url(another)
    assert not source_for_url(candidate)

    monkeypatch.setenv(
        "PASTE_LINK_DISABLED_SOURCES",
        "  carroselsalvador.com ,    unknown.example ",
    )
    assert source_for_url(good) is None
    assert source_for_url(another)
    assert source_for_url(candidate) is None
    coverage = ledger.get_readiness()
    assert coverage["pilot_candidates"] == 10
    assert coverage["enabled_trial_domains"] == 13
    assert coverage["production_deploy_permitted"] is False
    with TestClient(staging.app) as client:
        h = client.get("/health").json()
        rows = {s["domain"]: s for s in client.get("/api/sources").json()["sources"]}
    assert h["sources_enabled"] == 13
    assert rows["carroselsalvador.com"]["enabled"] is False
    assert rows["julajups.sv"]["enabled"] is True
    assert rows["autosale.com.sv"]["enabled"] is False

def test_coverage_exposes_next_integration_queue_without_unlocking_anything():
    with TestClient(staging.app) as client:
        response = client.get("/api/coverage")
    assert response.status_code == 200
    data = response.json()
    queue = data["next_wave"]
    assert len(queue) >= 9
    assert [x["rank"] for x in queue] == list(range(1, len(queue) + 1))
    assert queue[0]["source"] == "EasyCar"
    assert queue[1]["source"] == "Credipro"
    assert all(x["blocker"] and x["acceptance"] for x in queue)
    assert all(x["production_approved"] is False for x in queue)
    assert data["production_deploy_permitted"] is False
    assert not any("sample_url" in x for x in queue)
