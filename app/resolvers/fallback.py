"""Generic Open Graph resolver — last-resort fallback for any URL.

Useful if a listing comes from a site we don't have a specific resolver for.
Extracts og:title, og:image, og:description and tries to regex-extract
year/km/price/make from the title.
"""
from __future__ import annotations
import re
import asyncio
from urllib.parse import urljoin, urlsplit
import httpx
from ..safe_urls import is_public_url, public_dns_addresses
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

    # Validate each hop explicitly: httpx.follow_redirects=True can otherwise
    # fetch internal URLs via an attacker-controlled redirect.
    html = ""
    current_url = url
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False,
                                     trust_env=False,
                                     headers={"User-Agent": USER_AGENT}) as cli:
            for _ in range(6):
                if not is_public_url(current_url):
                    listing.errors.append("unsafe_url")
                    return listing
                hostname = urlsplit(current_url).hostname
                if not await asyncio.to_thread(public_dns_addresses, hostname):
                    listing.errors.append("unsafe_dns_destination")
                    return listing
                async with cli.stream("GET", current_url) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        redirect_to = r.headers.get("location")
                        if not redirect_to:
                            listing.errors.append("invalid_redirect")
                            return listing
                        current_url = urljoin(current_url, redirect_to)
                        continue
                    if r.status_code >= 400:
                        listing.errors.append(f"http {r.status_code}")
                        return listing
                    if "text/html" not in r.headers.get("content-type", "").lower():
                        listing.errors.append("not_html")
                        return listing
                    chunks = []
                    size = 0
                    async for chunk in r.aiter_bytes():
                        size += len(chunk)
                        if size > 1_000_000:
                            listing.errors.append("html_too_large")
                            return listing
                        chunks.append(chunk)
                    html = b"".join(chunks).decode("utf-8", errors="replace")
                    break
            else:
                listing.errors.append("too_many_redirects")
                return listing
    except httpx.HTTPError as e:
        listing.errors.append(f"http error: {e.__class__.__name__}")
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
