"""Carly v59 fail-closed retrieval insurance.

This is deliberately NOT a second inventory universe. If the primary focused
query unexpectedly returns zero, retry against the exact same GT certified
boundary, effective freshness policy and hard buyer constraints. A fallback
activation is always noisy in logs so it cannot silently hide a primary bug.
"""
from __future__ import annotations

import logging
from typing import Any

from . import carly_v59_demo_truth as v59

log = logging.getLogger("carly.v59.fallback")

GT_DEMO_CERTIFIED_SOURCES = {
    "atlas:www.agautoventas.com",
    "atlas:autogogt.com",
    "atlas:hgmotors.movilauto.com",
    "atlas:movilauto.com",
    "atlas:www.enlacesautomotrices.com",
}

_prior_query_rows = getattr(v59.v50.v46, "_ORIG_QUERY_ROWS", None)


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _same_exact_model(row: dict[str, Any], exact: Any) -> bool:
    if not exact:
        return True
    try:
        make, model, _ = exact
    except Exception:
        return False
    row_make = v59.v58.v28._norm(row.get("make"))
    wanted_make = v59.v58.v28._norm(make)
    row_model = v59.v58.v28._norm(row.get("model")).replace("-", "").replace(" ", "")
    wanted_model = v59.v58.v28._norm(model).replace("-", "").replace(" ", "")
    return row_make == wanted_make and bool(wanted_model) and (
        row_model == wanted_model or row_model.startswith(wanted_model) or wanted_model in row_model
    )


def _hard_filter(rows: list[dict[str, Any]], c: dict[str, Any], country: str) -> list[dict[str, Any]]:
    allowed = {
        v59.v58.v28._norm(x)
        for x in (c.get("allowed_brands") or [])
        if str(x).strip()
    }
    total_budget = _num(c.get("total_budget"))
    price_floor = _num(c.get("price_min"))
    monthly_max = _num(c.get("monthly_max"))
    price_cap = total_budget
    if monthly_max is not None:
        implied = monthly_max / 0.0238 * 1.03
        price_cap = min(price_cap, implied) if price_cap is not None else implied

    kept: list[dict[str, Any]] = []
    for row in rows or []:
        if str(row.get("country") or country).lower() != str(country or "").lower():
            continue
        if str(row.get("source") or "") not in GT_DEMO_CERTIFIED_SOURCES:
            continue
        if v59.v58.v28._norm(row.get("status")) != "staging":
            continue
        if v59.v58.v28._norm(row.get("listing_state")) != "indexed":
            continue
        if row.get("is_addressable") is not True:
            continue

        make = v59.v58.v28._norm(row.get("make"))
        if allowed and make not in allowed:
            continue
        if not _same_exact_model(row, c.get("exact")):
            continue

        year = _num(row.get("year"))
        if c.get("min_year") is not None and (year is None or year < float(c["min_year"])):
            continue

        if c.get("require_transmission") and v59.v31._transmission(row) != c.get("require_transmission"):
            continue
        if c.get("require_body") and v59.v31._body(row) != c.get("require_body"):
            continue

        price = _num(row.get("price_usd"))
        if price_floor is not None and (price is None or price < price_floor):
            continue
        if price_cap is not None and (price is None or price > price_cap):
            continue

        kept.append(row)
    return kept


def _fallback_rows(c: dict[str, Any], country: str) -> list[dict[str, Any]]:
    client = getattr(v59.v50.legacy, "supabase", None)
    if client is None:
        return []
    try:
        policy = v59.v50.freshness_policy(country)
        response = (
            client.table("scraped_listings")
            .select(v59.v31._SELECT)
            .eq("country", country)
            .eq("status", "staging")
            .eq("listing_state", "indexed")
            .eq("is_addressable", True)
            .gte("last_seen_at", str(policy["cutoff"]))
            .in_("source", sorted(GT_DEMO_CERTIFIED_SOURCES))
            .order("updated_at", desc=True)
            .limit(900)
            .execute()
        )
        broad = [dict(r) for r in (response.data or [])]
        kept = _hard_filter(broad, c, country)
        log.warning(
            "FALLBACK_RETRIEVAL_TRIGGERED country=%s freshness_mode=%s broad=%s kept=%s constraints=%s",
            country,
            policy.get("mode"),
            len(broad),
            len(kept),
            c,
        )
        return kept
    except Exception:
        log.exception("FALLBACK_RETRIEVAL_TRIGGERED failed_closed country=%s constraints=%s", country, c)
        return []


def _query_rows_with_safe_fallback(c: dict[str, Any], country: str) -> list[dict[str, Any]]:
    if _prior_query_rows is None:
        return []
    primary = _prior_query_rows(c, country)
    if primary:
        return primary
    return _fallback_rows(c, country)


def install() -> None:
    if _prior_query_rows is None:
        raise RuntimeError("Carly v59 fallback could not find active focused retrieval")
    if getattr(v59.v50.v46._ORIG_QUERY_ROWS, "_carly_v59_safe_fallback", False):
        return
    _query_rows_with_safe_fallback._carly_v59_safe_fallback = True
    v59.v50.v46._ORIG_QUERY_ROWS = _query_rows_with_safe_fallback
    log.warning("CARLY_V59_SAFE_FALLBACK installed same_certified_boundary=true loud_activation=true")
