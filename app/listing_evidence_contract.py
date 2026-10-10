"""Source-of-truth contract for Paste the Link.

A historical inventory record is useful for identity and photographs, but
must never silently become evidence of a current asking price.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import urlparse
import re

LIVE_SOURCES = frozenset({"live_direct", "live_authorized_feed"})
MAX_PRICE_AGE = timedelta(hours=24)


def listing_identity(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host == "encuentra24.com":
        match = re.search(r"/(\d{7,10})/?$", parsed.path)
        return ("encuentra24", match.group(1)) if match else None
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def current_asking_price(
    requested_url: str, observation: dict[str, Any], *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fail closed on stale/unattributed/mismatched price evidence.

    Observation keys: url, source_kind, captured_at, price, currency,
    access_status. The caller must furnish the evidence after a successful
    source fetch. A model estimate, Atlas snapshot, or seller-contact request
    is not a current source observation.
    """
    def unavailable(reason: str) -> dict[str, Any]:
        return {"value": None, "verified": False, "reason": reason}
    if not isinstance(observation, dict):
        return unavailable("missing_observation")
    if observation.get("source_kind") not in LIVE_SOURCES:
        return unavailable("not_live_source")
    if observation.get("access_status") != "ok":
        return unavailable("source_not_accessible")
    requested_identity = listing_identity(requested_url)
    observed_identity = listing_identity(str(observation.get("url") or ""))
    if not requested_identity or requested_identity != observed_identity:
        return unavailable("listing_identity_mismatch")
    observed_at = _parse_timestamp(observation.get("captured_at"))
    now = now or datetime.now(timezone.utc)
    if not observed_at or observed_at > now + timedelta(minutes=5):
        return unavailable("missing_or_invalid_timestamp")
    if now - observed_at > MAX_PRICE_AGE:
        return unavailable("stale_observation")
    if observation.get("currency") != "USD":
        return unavailable("currency_not_usd")
    raw_price = observation.get("price")
    if isinstance(raw_price, bool) or not isinstance(raw_price, (int, float)):
        return unavailable("invalid_price")
    if not (500 <= raw_price <= 200_000):
        return unavailable("price_out_of_range")
    return {
        "value": raw_price, "verified": True, "reason": None,
        "source_kind": observation["source_kind"],
        "source_url": observation["url"],
        "captured_at": observed_at.isoformat(),
    }
