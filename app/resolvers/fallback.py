"""Generic Open Graph resolver — last-resort fallback for any URL.

Useful if a listing comes from a site we don't have a specific resolver for.
Extracts og:title, og:image, og:description and tries to regex-extract
year/km/price/make from the title.
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
    listing = Listing(platform="unknown", url=url)

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT}) as cli:
            r = await cli.get(url)
            if r.status_code >= 400:
                listing.errors.append(f"http {r.status_code}")
                return listing
            html = r.text
    except httpx.HTTPError as e:
        listing.errors.append(f"http error: {e!s}")
        return listing

    og_title = _meta(html, "og:title") or _meta(html, "twitter:title") or ""
    og_image = _meta(html, "og:image") or _meta(html, "twitter:image") or ""
    og_desc = _meta(html, "og:description") or _meta(html, "twitter:description") or ""

    if og_title:
        listing.title = Field(value=og_title.strip()[:200], confidence="medium")
    if og_image:
        listing.photos.append(og_image)
    if og_desc:
        listing.description = Field(value=og_desc.strip()[:500], confidence="medium")

    haystack = (og_title + " " + og_desc).strip()
    yr = parsers.extract_year(haystack)
    if yr:
        listing.year = Field(value=yr[0], confidence="low")
    km = parsers.extract_km(haystack)
    if km:
        listing.km = Field(value=km[0], confidence="low")
    pr = parsers.extract_price_usd(haystack)
    if pr:
        listing.price_usd = Field(value=pr[0], confidence="low")
    mk = parsers.extract_make(haystack)
    if mk:
        listing.make = Field(value=mk[0], confidence="medium")
        md = parsers.extract_model(haystack, mk[0])
        if md:
            listing.model = Field(value=md[0], confidence="low")

    return listing
