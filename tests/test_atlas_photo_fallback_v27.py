from app.atlas_auto_repair import _visible_photo_fallbacks


def test_photo_fallback_prefers_og_image_and_skips_logo():
    html = """
    <html><head>
      <meta property="og:image" content="/uploads/cars/mazda-cx5.jpg">
    </head><body>
      <img src="/assets/logo.png">
    </body></html>
    """
    assert _visible_photo_fallbacks(html, "https://dealer.example/car/1") == [
        "https://dealer.example/uploads/cars/mazda-cx5.jpg"
    ]


def test_photo_fallback_uses_non_logo_img_when_metadata_missing():
    html = '<img src="/assets/logo.png"><img src="/uploads/cars/car-1.webp">'
    assert _visible_photo_fallbacks(html, "https://dealer.example/car/1") == [
        "https://dealer.example/uploads/cars/car-1.webp"
    ]
