"""Manual fallback may complete a buyer's comparison without claiming scraped facts."""
from fastapi.testclient import TestClient

from app.paste_link_manual_fallback import attach_manual_fallback
from app.paste_link_staging import app, STAGING_PAGE


def test_manual_fallback_only_present_in_staging_page():
    assert 'id="manual-helper"' in STAGING_PAGE
    assert 'Datos ingresados por ti · No verificados' in STAGING_PAGE
    assert 'no se envían ni guardan' not in STAGING_PAGE.lower() or "No se envían ni guardan" in STAGING_PAGE
    assert 'window.CT_manualFallback.show' in STAGING_PAGE
    assert 'window.CT_manualFallback.reset' in STAGING_PAGE
    assert 'No se pudo recuperar el anuncio' in STAGING_PAGE


def test_manual_helper_fails_closed_when_injection_structure_changes():
    try:
        attach_manual_fallback("<html></html>")
        assert False, "Expected ValueError for changed page template"
    except ValueError:
        pass
    try:
        attach_manual_fallback(STAGING_PAGE)
        assert False, "Expected ValueError for double injection"
    except ValueError:
        pass


def test_manual_fallback_does_not_provision_new_endpoints_or_storage():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'id="manual-helper"' in resp.text
    assert client.get("/buyer-intents").status_code in (404, 405)
    assert client.post("/buyer-intents", json={}).status_code == 404
