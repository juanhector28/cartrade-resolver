import asyncio
import pytest
from scripts import paste_link_smoke

def test_catalog_is_rejected_before_network():
    case = {"source_id":"sv-tucarro","url":"https://tucarro.sv/carros","expected":{"price_usd":5000}}
    result = asyncio.run(paste_link_smoke.check(case))
    assert not result["verified"]
    assert result["error"] == "url_not_supported_or_not_individual_listing"

def test_wrong_price_never_passes_smoke(monkeypatch):
    class FakeListing:
        def to_dict(self):
            return {"title":{"value":"Kia Sportage 2006"}, "year":{"value":2006},
                    "price_usd":{"value":45000}, "photos":["https://example.com/car.jpg"],"errors":[]}
    async def fake_resolve(url):
        return FakeListing()
    monkeypatch.setattr(paste_link_smoke.fallback,"resolve",fake_resolve)
    result=asyncio.run(paste_link_smoke.check({"source_id":"sv-carros-el-salvador",
         "url":"https://www.carroselsalvador.com/anuncios/kia-sportage-2006/",
         "expected":{"price_usd":5700,"year":2006}}))
    assert result["checks"]["price_usd"] is False
    assert result["verified"] is False

def test_matching_price_with_wrong_car_fails(monkeypatch):
    class WrongCar:
        def to_dict(self):
            return {"title":{"value":"Toyota Corolla 2006"}, "year":{"value":2006},
                    "price_usd":{"value":5700}, "photos":["https://example.com/car.jpg"], "errors":[]}
    async def fake_resolve(url):
        return WrongCar()
    monkeypatch.setattr(paste_link_smoke.fallback, "resolve", fake_resolve)
    result = asyncio.run(paste_link_smoke.check({
        "source_id":"sv-carros-el-salvador",
        "url":"https://www.carroselsalvador.com/anuncios/kia-sportage-2006/",
        "expected":{"price_usd":5700,"year":2006,"title_tokens":["Kia","Sportage","2006"]}
    }))
    assert result["checks"]["title_identity"] is False
    assert result["verified"] is False
