"""Generic Open Graph resolver — last-resort fallback for any URL.

Useful if a listing comes from a site we don't have a specific resolver for.
Extracts og:title, og:image, og:description and tries to regex-extract
year/km/price/make from the title.
"""
from __future__ import annotations
import re
import json
import httpx
from bs4 import BeautifulSoup
from .base import Listing, Field
from .. import parsers

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _meta(html: str, prop: str) -> str | None:
    """Support normal HTML attribute ordering and both quote styles."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    value = tag.get("content") if tag else None
    return str(value).strip() if value else None


def _structured_price(html: str) -> float | None:
    """Use listing-local schema.org offers, never prices from related ads."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            root = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        todo = [root]
        while todo:
            obj = todo.pop()
            if isinstance(obj, list):
                todo.extend(obj)
                continue
            if not isinstance(obj, dict):
                continue
            todo.extend(obj.get("@graph", []) if isinstance(obj.get("@graph"), list) else [])
            kind = obj.get("@type")
            kinds = [str(item).lower() for item in kind] if isinstance(kind, list) else [str(kind).lower()]
            if not any(k in {"product", "vehicle", "car"} for k in kinds):
                continue
            offers = obj.get("offers")
            if isinstance(offers, list):
                offers = next((o for o in offers if isinstance(o, dict)), None)
            if not isinstance(offers, dict):
                continue
            if str(offers.get("priceCurrency") or "").upper() != "USD":
                continue
            raw = offers.get("price")
            try:
                price = float(str(raw).replace(",", ""))
            except (ValueError, TypeError):
                continue
            if 500 <= price <= 200000:
                return price
    return None

async def resolve(url: str) -> Listing:
    listing = Listing(platform="unknown", url=url)

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False,
                                     headers={"User-Agent": USER_AGENT}) as cli:
            r = await cli.get(url)
            # Avoid automatic cross-origin redirects (SSRF and provenance confusion).
            if 300 <= r.status_code < 400:
                listing.errors.append("redirect not followed; source requires review")
                return listing
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
    structured_price = _structured_price(html)
    if structured_price is not None:
        listing.price_usd = Field(value=structured_price, confidence="high")
    pr = parsers.extract_price_usd(og_title) if structured_price is None else None
    if pr:
        listing.price_usd = Field(value=pr[0], confidence="low")
    mk = parsers.extract_make(haystack)
    if mk:
        listing.make = Field(value=mk[0], confidence="medium")
        md = parsers.extract_model(haystack, mk[0])
        if md:
            listing.model = Field(value=md[0], confidence="low")

    return listing
