"""Facebook Marketplace resolver.

FB locks most data behind authentication. The public URL only exposes Open
Graph meta tags. We get foto principal + título reliably, sometimes a snippet
of description. Everything else the user must fill manually.

Crucially: NO authenticated fetches. We do not bypass FB's login wall. That
violates Meta's ToS and exposes the business to legal risk. We are honest
about the limited extraction.
"""
from __future__ import annotations
import re
import httpx
from .base import Listing, Field
from .. import parsers

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _meta(html: str, prop: str) -> str | None:
    pat = re.compile(
        rf'<meta[^>]*(?:property|name)=["\']{re.escape(prop)}["\'][^>]*content=["\']([^"\']+)["\']',
        re.IGNORECASE)
    m = pat.search(html)
    return m.group(1) if m else None


async def resolve(url: str) -> Listing:
    listing = Listing(platform="facebook", url=url)

    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT,
                                              "Accept-Language": "es-SV,es;q=0.9"}) as cli:
            r = await cli.get(url)
            if r.status_code >= 400:
                listing.errors.append(f"http {r.status_code}")
                return listing
            html = r.text
    except httpx.HTTPError as e:
        listing.errors.append(f"http error: {e!s}")
        return listing

    og_title = _meta(html, "og:title") or ""
    og_image = _meta(html, "og:image") or ""
    og_desc = _meta(html, "og:description") or ""

    if og_title:
        # FB titles look like "1996 Toyota Hilux for $5,500 in San Salvador..."
        listing.title = Field(value=og_title.strip()[:200], confidence="high")
    if og_image:
        listing.photos.append(og_image)
    if og_desc:
        listing.description = Field(value=og_desc.strip()[:500], confidence="medium")

    # Parse what we can from title + description
    haystack = (og_title + " " + og_desc).strip()
    listing.year = parsers.to_field(parsers.extract_year(haystack))
    listing.km = parsers.to_field(parsers.extract_km(haystack))
    listing.price_usd = parsers.to_field(parsers.extract_price_usd(haystack))
    listing.transmission = parsers.to_field(parsers.extract_transmission(haystack))
    listing.fuel = parsers.to_field(parsers.extract_fuel(haystack))
    listing.make = parsers.to_field(parsers.extract_make(haystack))
    if listing.make:
        listing.model = parsers.to_field(parsers.extract_model(haystack, listing.make.value))

    # Adjust confidence: FB extraction is best-effort, downgrade non-OG fields
    for fld_name in ("year", "km", "price_usd", "transmission", "fuel"):
        fld = getattr(listing, fld_name)
        if fld and fld.confidence == "high":
            fld.confidence = "medium"

    if not og_title and not og_image:
        listing.errors.append("Facebook returned no Open Graph data (may be login-walled)")

    return listing
