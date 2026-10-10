import pytest
from app import platforms

@pytest.mark.parametrize("domain", [
    "caragencia.com", "carros.com", "motorasv.com", "tucarro.sv",
    "autospublicidad.com", "carroselsalvador.com", "disazautos.com",
    "nissanelsalvador.com",
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
