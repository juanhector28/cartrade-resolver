"""Contract tests for the isolated Carly Paste the Link staging service."""
from fastapi.testclient import TestClient
from app import paste_link_staging as staging
from app.resolvers.base import Field, Listing

VALID = "https://www.carroselsalvador.com/anuncios/kia-sportage-2006/"


def test_staging_health_and_ui():
    with TestClient(staging.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["storage"] is False
        page = client.get("/")
        assert page.status_code == 200
        assert 'Pega el link' in page.text
        assert 'id="photo"' in page.text
        assert 'img.onload' in page.text
        assert 'img.onerror' in page.text


def test_only_single_public_domain_allowed():
    assert staging.is_pilot_listing(VALID)
    for url in [
        "http://www.carroselsalvador.com/anuncios/kia-sportage-2006/",
        "https://www.carroselsalvador.com.evil.example/anuncios/abc/",
        "https://127.0.0.1/anuncios/abc/",
        "https://www.carroselsalvador.com/anuncios/",
        "https://www.carroselsalvador.com/",
        "https://user:pwd@www.carroselsalvador.com/anuncios/test/",
        "https://www.carroselsalvador.com:8443/anuncios/test/",
    ]:
        assert not staging.is_pilot_listing(url), url


def test_valid_pilot_response_never_persisted(monkeypatch):
    async def yes(url): return True
    async def good(url):
        return Listing(platform="unknown", url=url,
                       title=Field("KIA Sportage 2006", "medium"),
                       year=Field(2006, "medium"),
                       price_usd=Field(5700, "medium"),
                       km=Field(160934, "medium"),
                       photos=["https://example.com/kia.jpg"])
    monkeypatch.setattr(staging, "robots_allows", yes)
    monkeypatch.setattr(staging.fallback, "resolve", good)
    staging._limits.clear()
    with TestClient(staging.app) as client:
        r = client.post("/api/resolve", json={"url":VALID})
    assert r.status_code == 200
    data = r.json()
    assert data["price_usd"] == 5700 and data["km"] == 160934
    assert data["photos"] == ["https://example.com/kia.jpg"]
    assert data["saved"] is False and data["pilot_readonly"] is True
    assert data["photo_url_verified"] is False


def test_mismatched_or_missing_price_does_not_look_successful(monkeypatch):
    async def yes(url): return True
    async def missing(url):
        return Listing(platform="unknown", url=url, title=Field("KIA Sportage", "medium"))
    monkeypatch.setattr(staging, "robots_allows", yes)
    monkeypatch.setattr(staging.fallback, "resolve", missing)
    staging._limits.clear()
    with TestClient(staging.app) as client:
        r = client.post("/api/resolve", json={"url":VALID})
    assert r.status_code == 422


def test_rate_limit(monkeypatch):
    staging._limits.clear()
    for i in range(staging.MAX_PER_IP):
        assert staging.rate_check("127.0.0.1", now=1000)
    assert not staging.rate_check("127.0.0.1", now=1000)
    assert staging.rate_check("127.0.0.1", now=1000 + staging.WINDOW + 1)
