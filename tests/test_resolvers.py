"""Smoke tests against real URLs.

Run with:
    pip install pytest pytest-asyncio
    RESOLVER_DEV=1 pytest tests/ -v

These hit the live network. Skip them in CI unless you have a stable
testing environment.
"""
import pytest
import asyncio
from app.resolvers import encuentra24, olx, facebook, mercadolibre, fallback
from app import platforms

pytestmark = pytest.mark.asyncio


# ─── Platform detection ─────────────────────────────────────────

def test_detect_encuentra24():
    assert platforms.detect("https://www.encuentra24.com/el-salvador-es/autos/x") == "encuentra24"

def test_detect_olx_br():
    assert platforms.detect("https://www.olx.com.br/vi/1234") == "olx"

def test_detect_olx_sv():
    assert platforms.detect("https://www.olx.com.sv/anuncio/xyz") == "olx"

def test_detect_facebook():
    assert platforms.detect("https://www.facebook.com/marketplace/item/123/") == "facebook"

def test_detect_mercadolibre():
    assert platforms.detect("https://articulo.mercadolibre.com.sv/MLE-12345-x_JM") == "mercadolibre"

def test_detect_unknown():
    assert platforms.detect("https://random.example.com/page") == "unknown"

def test_is_allowed_yes():
    assert platforms.is_allowed("https://www.encuentra24.com/el-salvador-es/autos/x")
    assert platforms.is_allowed("https://www.olx.com.br/vi/1234")
    assert platforms.is_allowed("https://www.facebook.com/marketplace/item/123/")

def test_is_allowed_no():
    assert not platforms.is_allowed("https://random.example.com/page")
    assert not platforms.is_allowed("https://evil.com/redirect")


# ─── Live integration tests ────────────────────────────────────

ENC24_URLS = [
    "https://www.encuentra24.com/el-salvador-es/autos-usados/honda-hr-v-2024/31743871",
    "https://www.encuentra24.com/el-salvador-es/autos-usados/mitsubishi-outlander-sport-2022/32287004",
    "https://www.encuentra24.com/el-salvador-es/autos-usados/bonito-toyota-hilux-3-o-turbo-intercooler-poco-uso/32434900",
]

OLX_URLS = [
    "https://www.olx.com.br/vi/1506826467",
]

FB_URLS = [
    "https://www.facebook.com/marketplace/item/26621220917580878/",
    "https://www.facebook.com/marketplace/item/2574142266338532/",
]


@pytest.mark.parametrize("url", ENC24_URLS)
async def test_encuentra24_live(url):
    listing = await encuentra24.resolve(url)
    assert listing.platform == "encuentra24"
    assert listing.title is not None, f"no title for {url}"
    assert len(listing.photos) > 0, f"no photos for {url}"
    # At least one of year/make should be extracted
    assert listing.year is not None or listing.make is not None


@pytest.mark.parametrize("url", OLX_URLS)
async def test_olx_live(url):
    listing = await olx.resolve(url)
    assert listing.platform == "olx"
    # OLX may fail due to bot detection; we only assert it didn't crash
    print(f"OLX result for {url}:")
    print(f"  title={listing.title}")
    print(f"  errors={listing.errors}")


@pytest.mark.parametrize("url", FB_URLS)
async def test_facebook_live(url):
    listing = await facebook.resolve(url)
    assert listing.platform == "facebook"
    # FB may return nothing (login-walled); we only assert it didn't crash
    print(f"FB result for {url}:")
    print(f"  title={listing.title}")
    print(f"  photos={len(listing.photos)}")
    print(f"  errors={listing.errors}")


# ─── Parser unit tests ──────────────────────────────────────────

from app import parsers

def test_extract_year():
    assert parsers.extract_year("Honda Civic 2020 automatic")[0] == 2020
    assert parsers.extract_year("Toyota Hilux 1995")[0] == 1995
    assert parsers.extract_year("no year here") is None

def test_extract_make():
    r = parsers.extract_make("Honda Civic 2020")
    assert r[0] == "Honda"
    r = parsers.extract_make("Mercedes Benz C200")
    assert r[0] == "Mercedes Benz"

def test_extract_km():
    assert parsers.extract_km("28,000 km")[0] == 28000
    assert parsers.extract_km("kilometraje5,790")[0] == 5790
    assert parsers.extract_km("km: 12000")[0] == 12000

def test_extract_price():
    assert parsers.extract_price_usd("$ 28,500")[0] == 28500
    assert parsers.extract_price_usd("USD 14,000")[0] == 14000
    assert parsers.extract_price_usd("price is 5500 USD")[0] == 5500

def test_extract_transmission():
    assert parsers.extract_transmission("car is Automatic")[0] == "Automático"
    assert parsers.extract_transmission("Manual 5spd")[0] == "Manual"

def test_extract_fuel():
    assert parsers.extract_fuel("Gasolina")[0] == "Gasolina"
    assert parsers.extract_fuel("diesel turbo")[0] == "Diésel"
