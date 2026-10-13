import pytest
from app.financing_vehicle_context import create_vehicle_context

URL = "https://www.julajups.sv/anuncio/toyota-4-runner-trd-2019-4x4-N3tSneYO52"

def test_vehicle_context_preserves_original_listing():
    context = create_vehicle_context(url=URL, title="TOYOTA 4 RUNNER TRD 2019 4X4", price_usd=27500, year=2019)
    assert context == {
        "schema_version": 1, "source_url": URL, "title": "TOYOTA 4 RUNNER TRD 2019 4X4",
        "price_usd": 27500, "year": 2019, "financing_status": "not_started",
    }
    assert "approved" not in context
    assert "customer" not in context

@pytest.mark.parametrize("url", [
    "http://julajups.sv/anuncio/123",
    "https://user:pw@julajups.sv/anuncio/123",
    "file:///etc/passwd",
])
def test_reject_invalid_vehicle_link(url):
    with pytest.raises(ValueError):
        create_vehicle_context(url=url, title="Toyota", price_usd=27500, year=2019)

@pytest.mark.parametrize("price", [-1, 0, 250, 999999, True])
def test_reject_invalid_price(price):
    with pytest.raises(ValueError):
        create_vehicle_context(url=URL, title="Toyota", price_usd=price, year=2019)
