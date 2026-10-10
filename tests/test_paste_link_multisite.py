"""Tests for staging source registry and experimental price isolation."""
from app.paste_link_source_registry import SOURCES, source_for_url
from app.resolvers.fallback import parse_html

def test_multisite_exact_allowed_shapes():
    assert source_for_url("https://www.carroselsalvador.com/anuncios/kia-sportage-2006/")
    assert source_for_url("https://tucarro.sv/ford-expedition/63f2c0e8")
    assert source_for_url("https://caragencia.com/car-finder/2023-chevrolet-trailblazer")
    assert source_for_url("https://carros.com/car/b81740f31aee4629b3c8d1f7302a804f-p86776/")
    assert sum(bool(x["enabled"]) for x in SOURCES.values()) == 4

def test_multisite_rejects_catalog_open_redirects_and_unknown():
    for url in [
        "https://tucarro.sv/carros",
        "https://tucarro.sv/carros/ford",
        "https://tucarro.sv/blog",
        "https://nissanelsalvador.com/",
        "https://motorasv.com/cars",
        "https://carros.com/car-prices/honda/civic/",
        "https://caragencia.com/car-finder/",
        "https://carros.com.evil.test/car/b81740f31aee4629b3c8d1f7302a804f-p86776/",
        "https://tucarro.sv:8443/ford-expedition/63f2c0e8",
        "https://tucarro.sv/ford-expedition/63f2c0e8?return=http://127.0.0.1",
        "https://user:pass@tucarro.sv/ford-expedition/63f2c0e8",
        "http://tucarro.sv/ford-expedition/63f2c0e8",
    ]:
        assert source_for_url(url) is None, url

def test_tucarro_listing_prefers_primary_asking_price_over_seller_notes():
    html = (
      '<meta property="og:title" content="Ford Expedition 2018">'
      '<meta property="og:image" content="https://example.com/ford.jpg">'
      '<h1>Ford Expedition 2018</h1><div>Publicado hace 3 días</div>'
      '<div>$16,500</div><div>300,000 km</div>'
      '<section>Descripcion: vendedor dice $17,500 negociable.</section>'
      '<h2>Más carros</h2><div>$20,000</div>'
    )
    listing = parse_html("https://tucarro.sv/ford-expedition/63f2c0e8",html)
    assert listing.price_usd.value == 16500
    assert listing.km.value == 300000
    assert listing.photos

def test_caragencia_price_from_listing_price_not_seller_notes():
    html = (
      '<meta property="og:title" content="2023 Chevrolet TrailBlazer">'
      '<h1>2023 Chevrolet TrailBlazer</h1><div>Seller notes</div>'
      '<div>41,000 Millas reales Precio $15000</div>'
      '<h3>Listing Price</h3><div>USD 13,900</div><div>Recomendaciones USD 99,000</div>'
    )
    listing = parse_html("https://caragencia.com/car-finder/2023-chevrolet-trailblazer",html)
    assert listing.price_usd.value == 13900
    assert listing.km.value == 65983

def test_carros_com_current_listing_section_over_related_cars():
    html = (
      '<meta property="og:title" content="Honda Civic • 2015">'
      '<h1>Honda Civic • 2015 • 125837 km</h1>'
      '<p>Cash</p><p>$ 9,500 USD</p>'
      '<h3>Vehicle Details</h3><div>Mileage</div><div>125837 km</div>'
      '<h3>Description</h3><p>Comparable $12,000 USD</p>'
    )
    listing = parse_html("https://carros.com/car/b81740f31aee4629b3c8d1f7302a804f-p86776/",html)
    assert listing.price_usd.value == 9500
    assert listing.km.value == 125837
