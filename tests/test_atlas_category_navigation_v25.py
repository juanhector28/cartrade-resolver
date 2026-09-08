from app.atlas_listing_validity import listing_validity
from app.atlas_manifest_runner import _is_category_url


def _vehicle(url: str):
    return {
        "url": url,
        "make": "Toyota",
        "model": "RAV4",
        "year": 2022,
        "price_usd": 22500,
    }


def test_make_category_url_is_navigation():
    assert _is_category_url("https://movilauto.com/buscador/marca/kia")
    assert _is_category_url("https://movilauto.com/buscador/marca/mercedes-benz/")
    assert not _is_category_url("https://movilauto.com/vehiculo/toyota-rav4-2022")


def test_navigation_rows_do_not_dilute_listing_coverage():
    rows = [_vehicle(f"https://movilauto.com/vehiculo/{i}") for i in range(8)]
    rows += [
        {"url": "https://movilauto.com/buscador/marca/kia"},
        {"url": "https://movilauto.com/buscador/marca/maxus"},
        {"url": "https://movilauto.com/buscador/marca/mercedes-benz"},
        {"url": "https://movilauto.com/buscador/marca/jim"},
    ]
    out = listing_validity(rows, current_year=2026)
    assert out["raw_count"] == 12
    assert out["excluded_navigation_count"] == 4
    assert out["total_count"] == 8
    assert out["valid_count"] == 8
    assert out["valid_coverage_pct"] == 100.0
    assert out["passes_threshold"] is True
