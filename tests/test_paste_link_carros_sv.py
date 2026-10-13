from app.resolvers.fallback import parse_html


def test_carros_el_salvador_price_and_miles_converted_to_km():
    html = (
        '<meta property="og:title" content="KIA Sportage 2006">'
        '<meta property="og:image" content="https://example.com/kia.jpg">'
        '<section><strong>US$5,700</strong><h1>KIA Sportage 2006</h1>'
        '<dl><dt>Recorrido</dt><dd>100000 mi</dd></dl></section>'
        '<h2>Anuncios similares</h2><span>US$8,500</span>'
    )
    listing = parse_html(
        "https://www.carroselsalvador.com/anuncios/kia-sportage-2006/", html
    )
    assert listing.price_usd.value == 5700
    assert listing.km.value == 160934
    assert len(listing.photos) == 1


def test_carros_el_salvador_ignores_price_after_heading():
    html = (
        '<meta property="og:title" content="KIA Sportage 2006">'
        '<h1>KIA Sportage 2006</h1><h2>Similares</h2><span>US$8,500</span>'
    )
    listing = parse_html(
        "https://www.carroselsalvador.com/anuncios/kia-sportage-2006/", html
    )
    assert listing.price_usd is None


def test_other_site_does_not_use_sv_specific_price_rule():
    html = (
        '<meta property="og:title" content="KIA Sportage 2006">'
        '<strong>US$5,700</strong><h1>KIA Sportage 2006</h1>'
    )
    listing = parse_html("https://carros.com/car/abc/", html)
    assert listing.price_usd is None
