import os

os.environ.setdefault("REQUIREMENTS_DB", "/tmp/carly_v32_requirements.db")
os.environ.setdefault("CACHE_DB", "/tmp/carly_v32_cache.db")

from app import main_v32 as v32


def test_recent_500_dollar_sentra_is_price_anomaly():
    card = {"make": "Nissan", "model": "Sentra", "year": 2020, "price_usd": 500, "body_type": "sedan"}
    assert v32._price_anomaly(card, [card])


def test_recent_1200_dollar_rav4_is_price_anomaly():
    card = {"make": "Toyota", "model": "RAV4", "year": 2020, "price_usd": 1200, "body_type": "suv"}
    assert v32._price_anomaly(card, [card])


def test_peer_median_catches_suspicious_hilux_discount():
    bad = {"make": "Toyota", "model": "Hilux", "year": 2021, "price_usd": 7000, "body_type": "pickup"}
    rows = [
        bad,
        {"make": "Toyota", "model": "Hilux", "year": 2021, "price_usd": 16500, "body_type": "pickup"},
        {"make": "Toyota", "model": "Hilux", "year": 2022, "price_usd": 18000, "body_type": "pickup"},
        {"make": "Toyota", "model": "Hilux", "year": 2020, "price_usd": 17000, "body_type": "pickup"},
    ]
    assert v32._price_anomaly(bad, rows)


def test_normal_corolla_is_not_price_anomaly():
    card = {"make": "Toyota", "model": "Corolla", "year": 2023, "price_usd": 12000, "body_type": "sedan"}
    rows = [
        card,
        {"make": "Toyota", "model": "Corolla", "year": 2022, "price_usd": 11000, "body_type": "sedan"},
        {"make": "Toyota", "model": "Corolla", "year": 2024, "price_usd": 14500, "body_type": "sedan"},
        {"make": "Toyota", "model": "Corolla", "year": 2023, "price_usd": 13500, "body_type": "sedan"},
    ]
    assert not v32._price_anomaly(card, rows)


def test_corolla_cross_is_suv_not_sedan():
    card = {"make": "Toyota", "model": "Corolla Cross", "year": 2024, "body_type": "suv"}
    assert v32._body(card) == "suv"


def test_corolla_im_is_hatchback_not_sedan():
    card = {"make": "Toyota", "model": "Corolla iM", "year": 2018, "body_type": "sedan"}
    assert v32._body(card) == "hatchback"


def test_only_sedan_rejects_corolla_cross():
    c = v32.v31._constraints({"messages": [{"role": "user", "content": "Quiero únicamente sedán automático. Máximo US$400 al mes."}], "country": "sv"})
    card = {"make": "Toyota", "model": "Corolla Cross", "year": 2024, "price_usd": 13800, "monthly_est": 328, "body_type": "suv", "transmission": "Automática", "listing_state": "indexed", "is_addressable": True}
    assert not v32.v31._hard_ok(card, c)


def test_exact_miss_uses_alternative_constraints():
    c = v32.v31._constraints({"messages": [{"role": "user", "content": "Busco Honda CR-V 2024 o más nuevo. Muéstrame alternativas. Máximo US$450 al mes."}], "country": "sv"})
    effective = v32._effective_constraints(c, True)
    assert effective["exact"] is None
    assert effective["require_body"] == "suv"
