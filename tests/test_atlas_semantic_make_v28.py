from app.atlas_auto_repair import (
    _canonical_make,
    _plausible_make,
    _structured_vehicle_identity_fallbacks,
)


def test_rejects_related_vehicles_heading_as_make():
    assert not _plausible_make("Vehículos Relacionados")
    assert _canonical_make("Vehículos Relacionados") is None


def test_accepts_known_guatemala_market_makes():
    assert _canonical_make("Ford") == "Ford"
    assert _canonical_make("Mercedes-Benz") == "Mercedes-Benz"
    assert _canonical_make("JAC") == "JAC"
    assert _canonical_make("Changan") == "Changan"


def test_recovers_movilauto_brand_from_declared_og_metadata():
    html = """
    <html><head>
      <meta property="og:image"
        content="https://movilauto.com/api/og?title=Ford%20RANGER&amp;price=Quetzal%20130%2C000&amp;year=2014&amp;brand=Ford&amp;model=RANGER&amp;image=https%3A%2F%2Fexample.com%2Fford.jpg">
    </head><body>
      <h2>Vehículos Relacionados</h2>
    </body></html>
    """
    out = _structured_vehicle_identity_fallbacks(html)
    assert out["make"] == "Ford"
    assert out["model"] == "RANGER"
