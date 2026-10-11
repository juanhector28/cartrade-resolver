"""Versioned, non-persistent vehicle context for a future financing handoff.

This module does not submit customer data, originate credit or approve lending.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class FinancingVehicleContext:
    schema_version: int
    source_url: str
    title: str
    price_usd: int
    year: int | None
    financing_status: str = "not_started"


def create_vehicle_context(*, url: str, title: str, price_usd: int, year: int | None = None) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid source URL")
    if not title or len(title.strip()) > 200:
        raise ValueError("Vehicle title missing or too long")
    if isinstance(price_usd, bool) or not isinstance(price_usd, int) or not 500 <= price_usd <= 200000:
        raise ValueError("Invalid vehicle asking price")
    if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1950 <= year <= 2035):
        raise ValueError("Invalid model year")
    context = FinancingVehicleContext(schema_version=1, source_url=url, title=title.strip(), price_usd=price_usd, year=year)
    return asdict(context)
