"""Regression for the exact Julajups Toyota 4Runner listing reported by user.

The real public listing has a valid USD Product Offer but the preceding
description contains literal newlines and invalidates strict JSON-LD parsing.
"""
from app.resolvers.fallback import parse_html

TOYOTA_URL = "https://www.julajups.sv/anuncio/toyota-4-runner-trd-2019-4x4-N3tSneYO52"


def bad_control_html(price="27500", currency="USD"):
    return (
        '<meta property="og:title" content="TOYOTA 4 RUNNER TRD 2019 4X4">'
        '<meta property="og:image" content="https://www.julajups.sv/uploads/ads/706_09af06ae66b253bb968cb9a809f87025.webp">'
        '<script type="application/ld+json">{'
        '"@context":"https://schema.org","@type":"Product",'
        '"name":"TOYOTA 4 RUNNER TRD 2019 4X4",'
        '"description":"Toyota 4Runner TRD PRO\nAutomática Secuencial",'
        '"offers":{"@type":"Offer","price":"' + price + '",'
        '"priceCurrency":"' + currency + '","availability":"https://schema.org/InStock"}'
        '}</script>'
    )


def test_exact_toyota_listing_retrieves_current_asking_price_from_malformed_json_ld():
    listing = parse_html(TOYOTA_URL, bad_control_html())
    assert listing.title.value == "TOYOTA 4 RUNNER TRD 2019 4X4"
    assert listing.price_usd.value == 27500
    assert listing.price_usd.confidence == "high"
    assert listing.year.value == 2019
    assert len(listing.photos) == 1
    assert listing.errors == []


def test_only_julajups_tolerates_unescaped_json_controls():
    listing = parse_html(
        "https://other.example/anuncio/toyota-4-runner-trd-2019-4x4-N3tSneYO52",
        bad_control_html(),
    )
    assert listing.price_usd is None


def test_no_invented_price_if_currency_is_not_usd_or_price_missing():
    listing = parse_html(TOYOTA_URL, bad_control_html(currency="EUR"))
    assert listing.price_usd is None
    listing = parse_html(TOYOTA_URL, bad_control_html(price=""))
    assert listing.price_usd is None


def test_julajups_existing_valid_json_ld_still_works():
    html = (
        '<meta property="og:title" content="Subaru Impreza, Rs, 2006 awd">'
        '<script type="application/ld+json">{"@type":"Product",'
        '"name":"Subaru Impreza, Rs, 2006 awd",'
        '"offers":{"@type":"Offer","price":4000,"priceCurrency":"USD"}}'
        '</script>'
    )
    listing = parse_html(
        "https://www.julajups.sv/anuncio/subaru-impreza-rs-2006-awd-pxODLWUM9S",
        html,
    )
    assert listing.price_usd.value == 4000
