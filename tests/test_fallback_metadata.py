"""Generic resolver metadata regressions. Pure parsing, no outbound requests."""
from app.resolvers.fallback import _meta


def test_meta_attribute_order():
    html = '<meta content="Toyota &amp; Honda" property="og:title">'
    assert _meta(html, "og:title") == "Toyota & Honda"


def test_meta_single_quotes_and_name():
    html = "<meta content='https://img.example/car.jpg' name='twitter:image'>"
    assert _meta(html, "twitter:image") == "https://img.example/car.jpg"


def test_missing_meta():
    assert _meta("<html></html>", "og:title") is None
