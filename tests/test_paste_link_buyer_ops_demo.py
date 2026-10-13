"""Staging buyer ops preview: fake data only, no real database or leads."""
from fastapi.testclient import TestClient

from app.paste_link_staging import app


def test_preview_is_clearly_fictitious_and_without_buyer_contacts():
    response = TestClient(app).get("/ops/solicitudes")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "noindex" in response.headers["x-robots-tag"]
    assert "STAGING · DEMOSTRACIÓN · DATOS FICTICIOS" in response.text
    assert "Vista previa sin autenticación" in response.text
    assert "Toyota 4Runner TRD 2019 · ejemplo" in response.text
    assert 'buyer_contact:""' in response.text
    assert "SUPABASE_SERVICE_ROLE_KEY" not in response.text
    assert "localStorage" not in response.text
    assert "sessionStorage" not in response.text


def test_staging_does_not_offer_buyer_contact_api():
    client = TestClient(app)
    assert client.get("/ops/api/solicitudes").status_code == 404
    assert client.post("/buyer-intents", json={}).status_code == 404
    assert client.patch("/ops/api/solicitudes/00000000-0000-4000-8000-000000000001", json={"status": "closed"}).status_code == 404
