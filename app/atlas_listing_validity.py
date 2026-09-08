from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
import re
from urllib.parse import urlparse

CORE_FIELDS = ("make", "model", "year", "price_usd")
MIN_VALID_COVERAGE = 0.80
MIN_YEAR = 1950

_CATEGORY_PATH_PATTERNS = (
    re.compile(r"^/(?:buscador|buscar|search)/(?:marca|brand)/[^/]+/?$", re.I),
)


def _is_category_navigation(row: dict[str, Any] | None) -> bool:
    row = row or {}
    url = str(row.get("url") or row.get("source_url") or row.get("listing_url") or "").strip()
    if not url:
        return False
    path = urlparse(url).path or "/"
    return any(pattern.match(path) for pattern in _CATEGORY_PATH_PATTERNS)


def _nonempty(value: Any) -> bool:
    return value not in (None, "", [])


def is_valid_listing(row: dict[str, Any] | None, *, current_year: int | None = None) -> bool:
    """Canonical Atlas vehicle-listing validity contract.

    A listing is valid only when make/model/year/price are present, year is in a
    reasonable range, and normalized USD price is strictly positive. This is the
    single source of truth consumed by runtime quality gating and Publisher.
    Harness assertions consume the coverage emitted by these same functions
    rather than reimplementing the rules in another repository.
    """
    row = row or {}
    if not all(_nonempty(row.get(field)) for field in CORE_FIELDS):
        return False

    try:
        year = int(row.get("year"))
    except (TypeError, ValueError):
        return False
    if current_year is None:
        current_year = datetime.now(timezone.utc).year
    if year < MIN_YEAR or year > int(current_year) + 2:
        return False

    try:
        price = float(row.get("price_usd"))
    except (TypeError, ValueError):
        return False
    if price <= 0:
        return False

    return True


def listing_validity(rows: Iterable[dict[str, Any]] | None, *, current_year: int | None = None) -> dict[str, Any]:
    materialized = [row for row in (rows or []) if isinstance(row, dict)]
    excluded_navigation = [row for row in materialized if _is_category_navigation(row)]
    eligible = [row for row in materialized if not _is_category_navigation(row)]
    valid = [row for row in eligible if is_valid_listing(row, current_year=current_year)]
    total = len(eligible)
    coverage = (len(valid) / total) if total else 0.0
    return {
        "total_count": total,
        "valid_count": len(valid),
        "invalid_count": total - len(valid),
        "raw_count": len(materialized),
        "excluded_navigation_count": len(excluded_navigation),
        "valid_coverage": coverage,
        "valid_coverage_pct": round(coverage * 100, 2),
        "threshold": MIN_VALID_COVERAGE,
        "threshold_pct": int(MIN_VALID_COVERAGE * 100),
        "passes_threshold": bool(total and coverage >= MIN_VALID_COVERAGE),
        "valid_rows": valid,
    }
