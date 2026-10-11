import pytest
from app import platforms

@pytest.mark.parametrize("domain", [
    "caragencia.com", "carros.com", "motorasv.com", "tucarro.sv",
    "autospublicidad.com", "carroselsalvador.com", "disazautos.com",
])
def test_observed_sv_vehicle_sites_accepted(domain):
    url = f"https://www.{domain}/autos/vehicle-12345"
    assert platforms.is_allowed(url)
    assert platforms.detect(url) == "unknown"

@pytest.mark.parametrize("url", [
    "http://carros.com/autos/123",
    "https://carros.com.evil.example/123",
    "https://127.0.0.1/private",
    "https://localhost/admin",
    "https://user:pass@carros.com/123",
    "https://carros.com:8443/private",
    "file:///etc/passwd",
])
def test_untrusted_urls_denied(url):
    assert not platforms.is_allowed(url)

@pytest.mark.parametrize("url", [
    "https://motorasv.com/cars",
    "https://tucarro.sv/carros",
    "https://www.disazautos.com/importados",
    "https://www.carroselsalvador.com/anuncios/",
])
def test_known_catalog_pages_are_not_vehicle_listings(url):
    assert platforms.is_allowed(url)
    assert not platforms.is_listing_url(url)


@pytest.mark.parametrize("url", [
    "https://www.carroselsalvador.com/anuncios/kia-sportage-2006/",
    "https://caragencia.com/car-finder/2023-chevrolet-trailblazer",
    "https://carros.com/car/b81740f31aee4629b3c8d1f7302a804f-p86776/",
])
def test_individual_vehicle_routes_stay_available(url):
    assert platforms.is_listing_url(url)

def test_readonly_pilot_only_matches_supported_public_listing_host():
    assert platforms.is_readonly_public_pilot(
        "https://www.carroselsalvador.com/anuncios/kia-sportage-2006/"
    )
    assert not platforms.is_readonly_public_pilot("https://carros.com/car/abc")


def test_sv_public_pilot_rejects_catalog_and_homepage():
    assert not platforms.is_listing_url("https://www.carroselsalvador.com/")
    assert not platforms.is_listing_url("https://www.carroselsalvador.com/anuncios/")
    assert platforms.is_listing_url(
        "https://www.carroselsalvador.com/anuncios/ford-escape-2015-2/"
    )
