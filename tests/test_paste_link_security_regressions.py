"""Regression tests for source validation boundaries."""
import pytest
from app import platforms

@pytest.mark.parametrize("url", [
    "https://internal.carros.com/secret",
    "https://foo.caragencia.com/auto",
    "https://evil.julajups.sv/anuncio/toyota-4-runner-trd-2019-4x4-N3tSneYO52",
    "https://nissanelsalvador.com/",
])
def test_unverified_fetch_targets_are_rejected(url):
    assert not platforms.is_allowed(url)

@pytest.mark.parametrize("host", [
    "caragencia.com", "carros.com", "motorasv.com", "tucarro.sv",
    "autospublicidad.com", "carroselsalvador.com", "disazautos.com", "julajups.sv",
])
def test_new_sv_pilot_hosts_are_readonly(host):
    assert platforms.is_readonly_public_pilot(f"https://{host}/listing")
