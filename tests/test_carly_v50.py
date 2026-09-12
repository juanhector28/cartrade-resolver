from app import main_v50 as v50


def row(i, *, body="sedan", quality=50, year=2020):
    return {
        "id": i,
        "url": f"https://example.test/{i}",
        "body_type": body,
        "quality_score": quality,
        "year": year,
        "monthly_est": 300,
    }


def test_legacy_fallback_pool_is_bounded(monkeypatch):
    rows = [row(i, quality=i % 100, year=2010 + (i % 15)) for i in range(900)]
    monkeypatch.setattr(v50, "_ORIG_V31_QUERY", lambda c, country: rows)
    bounded = v50._bounded_legacy_query({"exact": None, "passengers": None}, "sv")
    assert len(bounded) == 180


def test_explicit_body_uses_tighter_interactive_cap(monkeypatch):
    rows = [row(i, body="suv" if i % 2 else "sedan") for i in range(900)]
    monkeypatch.setattr(v50, "_ORIG_V31_QUERY", lambda c, country: rows)
    bounded = v50._bounded_legacy_query({"exact": None, "require_body": "suv"}, "sv")
    assert len(bounded) == 144
    assert all(v50.v31._body(r) == "suv" for r in bounded)


def test_exact_search_is_not_bounded(monkeypatch):
    rows = [row(i) for i in range(250)]
    monkeypatch.setattr(v50, "_ORIG_V31_QUERY", lambda c, country: rows)
    exact = ("Toyota", "Corolla", "sedan")
    bounded = v50._bounded_legacy_query({"exact": exact}, "sv")
    assert bounded == rows
