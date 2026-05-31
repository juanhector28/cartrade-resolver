"""MercadoLibre resolver.

Uses the official public API. Item ID is embedded in the URL like:
  https://articulo.mercadolibre.com.sv/MLE-1234567890-honda-civic-2020-_JM
  → MLE1234567890

The API returns full structured data, no scraping needed.
"""
from __future__ import annotations
import re
import httpx
from .base import Listing, Field

API_BASE = "https://api.mercadolibre.com/items/"


def _extract_item_id(url: str) -> str | None:
    # Patterns: MLE-12345, MLA-12345, MLB-12345, MLM-12345, etc.
    m = re.search(r"\b(ML[A-Z])-?(\d{8,15})\b", url)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}"


async def resolve(url: str) -> Listing:
    listing = Listing(platform="mercadolibre", url=url)

    item_id = _extract_item_id(url)
    if not item_id:
        listing.errors.append("Could not extract MercadoLibre item ID from URL")
        return listing

    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.get(API_BASE + item_id)
            if r.status_code >= 400:
                listing.errors.append(f"ML API returned {r.status_code}")
                return listing
            d = r.json()
    except (httpx.HTTPError, ValueError) as e:
        listing.errors.append(f"ML API error: {e!s}")
        return listing

    if d.get("title"):
        listing.title = Field(value=str(d["title"])[:200], confidence="high")
    if d.get("price") is not None:
        currency = d.get("currency_id", "")
        try:
            p = int(float(d["price"]))
            conf = "high" if currency == "USD" else "medium"
            listing.price_usd = Field(value=p, confidence=conf)
        except (ValueError, TypeError):
            pass

    # Pictures
    for pic in (d.get("pictures") or []):
        url_ = pic.get("secure_url") or pic.get("url")
        if url_:
            listing.photos.append(url_)
    listing.photos = listing.photos[:12]

    # Attributes — ML returns a flat list of {id, name, value_name, ...}
    for attr in (d.get("attributes") or []):
        aid = attr.get("id", "")
        val = attr.get("value_name") or attr.get("value_struct", {})
        if isinstance(val, dict):
            val = val.get("number") or val.get("value")
        if val is None:
            continue
        val = str(val)
        if aid == "BRAND":
            listing.make = Field(value=val, confidence="high")
        elif aid == "MODEL":
            listing.model = Field(value=val, confidence="high")
        elif aid in ("ITEM_CONDITION", "VEHICLE_YEAR"):
            try:
                y = int(re.sub(r"\D", "", val))
                if 1990 <= y <= 2027:
                    listing.year = Field(value=y, confidence="high")
            except ValueError:
                pass
        elif aid == "KILOMETERS":
            try:
                km = int(re.sub(r"\D", "", val))
                if 0 < km < 1_000_000:
                    listing.km = Field(value=km, confidence="high")
            except ValueError:
                pass
        elif aid == "TRANSMISSION":
            listing.transmission = Field(value=val, confidence="high")
        elif aid == "FUEL_TYPE":
            listing.fuel = Field(value=val, confidence="high")

    # Description (separate endpoint)
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.get(API_BASE + item_id + "/description")
            if r.status_code == 200:
                dd = r.json()
                txt = dd.get("plain_text") or dd.get("text") or ""
                if txt:
                    listing.description = Field(value=txt.strip()[:500], confidence="high")
    except (httpx.HTTPError, ValueError):
        pass

    # Location
    loc = d.get("seller_address") or {}
    if loc:
        city = (loc.get("city") or {}).get("name") if isinstance(loc.get("city"), dict) else None
        state = (loc.get("state") or {}).get("name") if isinstance(loc.get("state"), dict) else None
        parts = [p for p in (city, state) if p]
        if parts:
            listing.location = Field(value=", ".join(parts), confidence="high")

    return listing
