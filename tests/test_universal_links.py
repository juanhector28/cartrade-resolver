"""Offline regression tests for universal public link acceptance.

Do not call third-party sites in CI. These tests prove URL gating and
redirect safety; live extraction still requires a separate smoke test.
"""
from unittest.mock import patch
import pytest
import httpx
from app import platforms
from app.resolvers import fallback


@pytest.mark.parametrize("url", [
    "https://crautos.com/autosusados/cardetail.cfm?c=1234",
    "https://www.encuentra24.com/el-salvador-es/autos-usados/test/33016406",
    "https://dealer.example.com/used/car-123",
])
def test_public_domains(url):
    assert platforms.is_allowed(url)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin",
    "http://10.0.0.10/internal",
    "http://169.254.169.254/latest/meta-data/",
    "http://localhost:8000/health",
    "file:///etc/passwd",
    "https://user:secret@example.com/car",
])
def test_unsafe_destinations(url):
    assert not platforms.is_allowed(url)


def test_platform_spoofing():
    assert platforms.detect("https://encuentra24.com.evil.example/car") == "unknown"


@pytest.mark.asyncio
async def test_redirect_into_private_network_is_refused():
    def handler(request):
        if request.url.host == "dealer.example.com":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        raise AssertionError("private endpoint must never be fetched")
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient
    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)
    with patch("app.resolvers.fallback.httpx.AsyncClient", side_effect=fake_client), patch(
        "app.resolvers.fallback.public_dns_addresses", return_value=True
    ):
        result = await fallback.resolve("https://dealer.example.com/car")
    assert "unsafe_url" in result.errors
