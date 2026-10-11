"""Anuto SV route and listing-local field contract for read-only staging."""
from app.paste_link_source_registry import SOURCES, source_for_url
from app.resolvers.fallback import parse_html

YARIS="https://sv.anuto.app/ad/se-vende-toyota-yaris-automatico-0nPyz4dvggGHLtrN8nVx"
TACOMA="https://sv.anuto.app/ad/toyota-tacoma-2021-Trgt028DJRkzLdjJO6d3"

def make_page(name: str, price: int, year: int, km: str):
    return (
      f'<meta property="og:title" content="{name} – ${price:,.0f} en La Libertad | Anuto">'
      f'<meta property="og:image" content="https://img.anuto.app/vehicles/{year}/car.jpg">'
      f'<h1>{name}</h1>'
      f'<div>Detalles</div><p>Estado Buen estado</p>'
      f'<div>Año</div><div>{year}</div>'
      f'<div>Kilómetros</div><div>{km}km</div>'
      f'<h2>Descripción</h2><p>La descripción dice 67 mil millas, no usar para campo km</p>'
      f'<h2>Anuncios relacionados</h2><p>Otro Toyota 2024 $65,000</p>'
    )

def test_anuto_route_exact_listing_only():
    assert SOURCES["sv.anuto.app"]["enabled"]
    assert source_for_url(YARIS)
    assert source_for_url(TACOMA)
    for url in [
        "https://sv.anuto.app/autos-vehiculos",
        "https://sv.anuto.app/ad/",
        "https://sv.anuto.app/ad/toyota-tacoma-2021-wrong",
        "https://evil.sv.anuto.app/ad/toyota-tacoma-2021-Trgt028DJRkzLdjJO6d3",
        TACOMA+"?callback=http://localhost",
        "http://sv.anuto.app/ad/toyota-tacoma-2021-Trgt028DJRkzLdjJO6d3",
    ]:
        assert source_for_url(url) is None, url

def test_yaris_local_year_and_mileage_not_missing_from_og():
    listing=parse_html(YARIS,make_page("Se vende Toyota Yaris automático",2500,2008,"135,000"))
    assert listing.title.value=="Se vende Toyota Yaris automático"
    assert listing.price_usd.value==2500
    assert listing.year.value==2008
    assert listing.km.value==135000
    assert len(listing.photos)==1

def test_tacoma_prefers_structured_kilometros_over_seller_miles():
    listing=parse_html(TACOMA,make_page("Toyota Tacoma 2021",23500,2021,"67,000"))
    assert listing.title.value=="Toyota Tacoma 2021"
    assert listing.price_usd.value==23500
    assert listing.year.value==2021
    assert listing.km.value==67000

def test_anuto_no_related_vehicle_price_used_when_listing_has_no_price():
    page=(
        '<h1>Toyota Tacoma 2021</h1><h2>Detalles</h2><div>Año 2021</div>'
        '<h2>Descripción</h2><p>Precio por consultar</p>'
        '<h2>Anuncios relacionados</h2><div>$25,000</div>'
    )
    listing=parse_html(TACOMA,page)
    assert listing.price_usd is None

def test_anuto_parser_isolated_from_other_domains():
    listing=parse_html("https://other.example/ad/tacoma-2021-Trgt028DJRkzLdjJO6d3",
                       make_page("Toyota Tacoma 2021",23500,2021,"67,000"))
    assert listing.km is None
