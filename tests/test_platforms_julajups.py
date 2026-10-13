"""Regression tests for host allowlist used by Paste Your Link."""
from app import platforms


def test_supported_julajups():
    assert platforms.is_allowed("https://www.julajups.sv/anuncio/toyota-4-runner-trd-2019-4x4-N3tSneYO52")
    assert platforms.detect("https://www.julajups.sv/anuncio/foo") == "unknown"


def test_reject_host_confusion():
    assert not platforms.is_allowed("https://julajups.sv.evil.example/anuncio/car")
    assert not platforms.is_allowed("http://127.0.0.1/admin")
    assert not platforms.is_allowed("https://user:pass@julajups.sv/anuncio/car")
    assert not platforms.is_allowed("ftp://julajups.sv/anuncio/car")
