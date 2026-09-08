from app.atlas_auto_repair import _url_vehicle_identity_fallbacks


def test_agautoventas_slug_recovers_core_identity():
    out = _url_vehicle_identity_fallbacks(
        "https://www.agautoventas.com/camioneta_0/mazda-cx5-grand-touring-fwd-m2016_4.html"
    )
    assert out == {
        "make": "Mazda",
        "model": "CX5 GRAND TOURING FWD",
        "year": 2016,
    }


def test_agautoventas_kia_slug_recovers_core_identity():
    out = _url_vehicle_identity_fallbacks(
        "https://www.agautoventas.com/camioneta_0/kia-sportage-lx-awd-m2020_0.html"
    )
    assert out["make"] == "Kia"
    assert out["model"] == "SPORTAGE LX AWD"
    assert out["year"] == 2020


def test_generic_navigation_url_does_not_invent_vehicle_identity():
    assert _url_vehicle_identity_fallbacks("https://example.com/vehiculos/mazda") == {}
    assert _url_vehicle_identity_fallbacks("https://example.com/blog/toyota-hilux") == {}
