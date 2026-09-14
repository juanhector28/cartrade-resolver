from __future__ import annotations

from app import carly_v59_safe_fallback as fb


def _row(**overrides):
    row = {
        "country": "gt",
        "source": "atlas:movilauto.com",
        "status": "staging",
        "listing_state": "indexed",
        "is_addressable": True,
        "make": "Honda",
        "model": "CR-V",
        "year": 2016,
        "price_usd": 12442.65,
        "monthly_est": 296,
        "transmission": None,
    }
    row.update(overrides)
    return row


def test_fallback_preserves_certified_boundary_and_hard_constraints():
    c = {
        "allowed_brands": ["Honda"],
        "require_body": "suv",
        "monthly_max": 450.0,
        "total_budget": None,
        "price_min": None,
    }
    rows = [
        _row(),
        _row(source="atlas:untrusted.example"),
        _row(status="atlas_shadow"),
        _row(listing_state="expired"),
        _row(is_addressable=False),
        _row(make="Toyota", model="RAV4"),
        _row(model="Civic"),
        _row(price_usd=25000),
    ]
    kept = fb._hard_filter(rows, c, "gt")
    assert kept == [rows[0]]


def test_fallback_does_not_fabricate_toyota_suv_from_certified_two():
    c = {
        "allowed_brands": ["Toyota"],
        "require_body": "suv",
        "monthly_max": 450.0,
        "total_budget": None,
        "price_min": None,
    }
    certified_toyotas = [
        _row(make="Toyota", model="AGYA", year=2022, price_usd=8245.16, monthly_est=196, transmission="Manual", source="atlas:hgmotors.movilauto.com"),
        _row(make="Toyota", model="YARIS L", year=2019, price_usd=10880.72, monthly_est=259, source="atlas:www.enlacesautomotrices.com"),
    ]
    assert fb._hard_filter(certified_toyotas, c, "gt") == []


def test_primary_nonempty_never_calls_fallback(monkeypatch):
    primary = [_row()]
    monkeypatch.setattr(fb, "_prior_query_rows", lambda c, country: primary)

    def explode(*args, **kwargs):
        raise AssertionError("fallback must not run when primary returns rows")

    monkeypatch.setattr(fb, "_fallback_rows", explode)
    assert fb._query_rows_with_safe_fallback({"allowed_brands": ["Honda"]}, "gt") is primary
