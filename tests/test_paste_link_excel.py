"""Excel Usados contract: on-page asking price, odometer and genuine gallery."""
from app.resolvers.fallback import parse_html
from app.paste_link_source_registry import SOURCES, source_for_url

DZIRE="https://usados.excelautomotriz.com/autos-el-salvador/suzuki-dzire-p-79aca/"
FUSO="https://usados.excelautomotriz.com/autos-el-salvador/fuso-fi-2025-26-15-unidades/"

def document(vehicle,price,year,km,photo="2026/09/IMG_6050-scaled.jpg"):
    return (
      "<title>Excel Automotriz Usados</title>"
      '<img src="https://usados.excelautomotriz.com/wp-content/themes/custom_theme/dist/images/logo.png" alt="logo">'
      '<div class="container"><h1>'+vehicle+'</h1></div>'
      '<div class="layer"><p>Precio <span>$ '+price+'</span></p></div>'
      '<div>Marca / Modelo: '+vehicle+'</div>'
      '<div>Año: '+str(year)+'</div>'
      '<p>Recorrido <span>'+str(km)+' Kilometros</span></p>'
      '<div class="item"><img src="https://usados.excelautomotriz.com/wp-content/uploads/'+photo+'" alt="slide"></div>'
      '<h3>SOLICITA TU CITA</h3>'
      '<div>Anuncios relacionados $ 95,000 2024 15 km</div>'
    )

def test_excel_route_candidate_must_remain_disabled_until_live_validation():
    assert not SOURCES["usados.excelautomotriz.com"]["enabled"]
    assert source_for_url(DZIRE) is None
    assert source_for_url(FUSO) is None

def test_excel_dzire_exact_labelled_price_year_km_and_gallery():
    listing=parse_html(DZIRE,document("SUZUKI DZIRE P 79ACA","13,000",2025,"48109"))
    assert listing.title.value == "SUZUKI DZIRE P 79ACA"
    assert listing.price_usd.value == 13000
    assert listing.price_usd.confidence == "high"
    assert listing.year.value == 2025
    assert listing.km.value == 48109
    assert listing.photos == [
        "https://usados.excelautomotriz.com/wp-content/uploads/2026/09/IMG_6050-scaled.jpg"
    ]

def test_excel_does_not_take_a_price_from_other_listings():
    html=(
      '<meta property="og:title" content="Related BMW - $95,000">'
      '<meta property="og:image" content="https://other.example/related-car.jpg">'
      '<script type="application/ld+json">{"@type":"Product","offers":'
      '{"@type":"Offer","priceCurrency":"USD","price":95000}}</script>'
      '<h1>SUZUKI DZIRE P 79ACA</h1><p>Año: 2025</p>'
      '<h2>SOLICITA TU CITA</h2><span>Relacionado $15,000</span>'
    )
    listing=parse_html(DZIRE,html)
    assert listing.price_usd is None
    assert listing.title is None
    assert listing.photos == []

def test_excel_never_returns_logo_or_external_photo_as_vehicle():
    html=document("SUZUKI DZIRE P 79ACA","13,000",2025,"48109").replace(
      "https://usados.excelautomotriz.com/wp-content/uploads/2026/09/IMG_6050-scaled.jpg",
      "https://bad.example/photos/other.jpg"
    )
    listing=parse_html(DZIRE,html)
    assert listing.price_usd.value == 13000
    assert listing.photos == []

def test_excel_blocks_non_vehicle_page_and_bad_price():
    listing=parse_html("https://usados.excelautomotriz.com/el-salvador/",
                       document("SUZUKI DZIRE P 79ACA","13,000",2025,"48109"))
    assert listing.price_usd is None
    listing=parse_html(DZIRE, document("SUZUKI DZIRE P 79ACA","100",2025,"48109"))
    assert listing.price_usd is None

def test_excel_kilometers_optional_and_not_inferred_from_related():
    html=document("SUZUKI DZIRE P 79ACA","13,000",2025,"48109")
    html=html.replace('<p>Recorrido <span>48109 Kilometros</span></p>','')
    listing=parse_html(DZIRE,html)
    assert listing.km is None
