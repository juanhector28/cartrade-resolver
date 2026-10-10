from app.resolvers.fallback import _meta, _structured_price


def test_meta_tag_can_put_content_before_property():
    html = '<meta content="2023 Chevrolet TrailBlazer USD 13,900" property="og:title">'
    assert _meta(html, "og:title") == "2023 Chevrolet TrailBlazer USD 13,900"


def test_product_offer_price_and_currency():
    html = """<script type="application/ld+json">
    {"@type":"Product","name":"Chevrolet TrailBlazer","offers":{"@type":"Offer","price":"13900","priceCurrency":"USD"}}
    </script>"""
    assert _structured_price(html) == 13900


def test_ignore_price_of_related_listing_or_aggregate():
    html = """<script type="application/ld+json">
    {"@type":"ItemList","itemListElement":[{"@type":"Product","offers":{"price":"45000","priceCurrency":"USD"}}]}
    </script>"""
    assert _structured_price(html) is None


def test_non_usd_currency_is_not_assumed_usd():
    html = '<script type="application/ld+json">{"@type":"Car","offers":{"price":120000,"priceCurrency":"GTQ"}}</script>'
    assert _structured_price(html) is None
