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


def test_site_specific_missing_price_messages_do_not_mask_extractor_status(monkeypatch):
    async def yes(url): return True
    async def no_price(url):
        return Listing(platform="unknown", url=url, title=Field("Vehículo de prueba 2024", "medium"))
    monkeypatch.setattr(staging, "robots_allows", yes)
    monkeypatch.setattr(staging.fallback, "resolve", no_price)
    staging._limits.clear()
    examples = [
        ("https://www.julajups.sv/anuncio/subaru-impreza-rs-2006-awd-pxODLWUM9S", "Julajups"),
        ("https://easycar.com.sv/car/109", "EasyCar"),
        ("https://crediq.com/sv/product/chery-tiggo-2-pro-luxury-rojo-2026/", "CrediQ"),
    ]
    with TestClient(staging.app) as client:
        for url, name in examples:
            res = client.post("/api/resolve", json={"url": url})
            assert res.status_code == 422
            assert name in res.json()["detail"]
            assert "precio" in res.json()["detail"].lower()


def test_eurosport_access_denial_is_not_presented_as_a_parser_failure(monkeypatch):
    async def no(url): return False
    async def unexpected(url):
        raise AssertionError("Listing request must not be made when robots check denies access.")
    monkeypatch.setattr(staging, "robots_allows", no)
    monkeypatch.setattr(staging.fallback, "resolve", unexpected)
    staging._limits.clear()
    with TestClient(staging.app) as client:
        res = client.post(
            "/api/resolve",
            json={"url": "https://www.eurosportautos.com/vehiculo/ford-bronco-sport-badlands-2024-4x4"},
        )
    assert res.status_code == 403
    assert "Eurosport Autos" in res.json()["detail"]
    assert "restricciones" in res.json()["detail"]


def test_source_chips_do_not_mark_untested_sites_validated():
    with TestClient(staging.app) as client:
        sources = {x["domain"]: x for x in client.get("/api/sources").json()["sources"]}
        html = client.get("/").text
    assert sources["easycar.com.sv"]["stage"] == "javascript_required"
    assert sources["eurosportautos.com"]["stage"] == "access_review"
    assert sources["crediq.com"]["stage"] == "access_review"
    assert 'const verified=x.stage==="browser_sample_verified"||x.stage==="browser_verified"' in html

def test_verified_sample_status_is_not_full_domain_certification():
    with TestClient(staging.app) as client:
        d={item["domain"]:item for item in client.get("/api/sources").json()["sources"]}
    assert d["sv.anuto.app"]["stage"]=="browser_sample_verified"
    assert d["julajups.sv"]["stage"]=="browser_sample_verified"
    assert d["usados.excelautomotriz.com"]["enabled"] is True
    assert d["crediq.com"]["stage"]=="access_review"
