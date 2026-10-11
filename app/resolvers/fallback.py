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

    return parse_html(url, html)


def _carroselsalvador_detail(html: str, listing: Listing) -> None:
    """Parse only the heading-adjacent price and labelled odometer on this domain."""
    from urllib.parse import urlparse
    host = (urlparse(listing.url).hostname or "").lower().removeprefix("www.")
    if host != "carroselsalvador.com":
        return
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return
    title = h1.get_text(" ", strip=True)
    if not re.search(r"\b(?:19|20)\d{2}\b", title):
        return
    for node in h1.find_all_previous(string=True, limit=24):
        match = re.fullmatch(r"\s*US\s*\$\s*([\d,]+)(?:\.00)?\s*", str(node), re.I)
        if match:
            price = int(match.group(1).replace(",", ""))
            if 500 <= price <= 200000:
                listing.price_usd = Field(value=price, confidence="medium")
                break
    text = soup.get_text(" ", strip=True)
    mileage = re.search(r"\bRecorrido\s*:?\s*([\d.,]+)\s*(mi|millas|km)\b", text, re.I)
    if mileage:
        raw = mileage.group(1).replace(",", "")
        try:
            distance = float(raw)
        except ValueError:
            return
        if 0 <= distance <= 2000000:
            km = round(distance * 1.609344) if mileage.group(2).lower() != "km" else round(distance)
            listing.km = Field(value=km, confidence="medium")

def _experimental_listing_detail(html: str, listing: Listing) -> None:
    """Site-local price/mileage, excluding related ads and seller free-text.

    These branches are exploratory: absence of authoritative listing-local price
    must stay missing, never fall back to a related-car or financing installment.
    """
    from urllib.parse import urlparse
    host = (urlparse(listing.url).hostname or "").lower().removeprefix("www.")
    if host not in {"tucarro.sv", "caragencia.com", "carros.com"}:
        return
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return
    text = soup.get_text(" ", strip=True)
    title = h1.get_text(" ", strip=True)
    if not re.search(r"\b(?:19|20)\d{2}\b", title):
        return

    price_match = None
    miles_match = None
    if host == "tucarro.sv":
        # Only the immediate heading-area facts, before seller notes/financing.
        next_fragments = [str(v).strip() for v in h1.find_all_next(string=True, limit=35)]
        facts = " ".join(next_fragments)
        price_match = re.search(r"(?<!\w)\$\s*([\d,]{3,})(?!\d)", facts)
        miles_match = re.search(r"\b([\d,]{2,})\s*(km|millas|mi)\b", facts, re.I)
    elif host == "caragencia.com":
        # Authoritative listing price, not the seller's arbitrary notes.
        price_match = re.search(r"\bListing Price\s+USD\s*([\d,]+)", text, re.I)
        # If the listing explicitly says miles we may normalize them.
        note = re.search(r"\bSeller notes\b(.{0,2500}?)\bListing Price\b", text, re.I | re.S)
        if note:
            miles_match = re.search(r"(?<![\d,])(\d[\d,]*)\s*(millas|mi|km)\b", note.group(1), re.I)
    else:  # carros.com
        # Use only the current page's header and Vehicle Details block.
        lead = text.split("Vehicle Details", 1)[0][:1600]
        price_match = re.search(r"\$\s*([\d,]+)\s*USD\b", lead, re.I)
        details = text.split("Vehicle Details", 1)
        if len(details) == 2:
            details = details[1].split("Description", 1)[0]
            miles_match = re.search(r"\bMileage\s*([\d,]+)\s*(km|mi|millas)\b", details, re.I)
    if price_match:
        try:
            price = int(price_match.group(1).replace(",", ""))
        except (ValueError, TypeError):
            price = None
        if price is not None and 500 <= price <= 200000:
            listing.price_usd = Field(value=price, confidence="medium")
    if host == "carros.com":
        # Prefer the listing's exact gallery over relative/default OG image.
        # Gallery photos may use protocol-relative or site-relative URLs.
        from urllib.parse import urljoin, urlparse as _urlparse, urlunparse
        display_name = h1.get_text(" ", strip=True).split("•")[0].strip().lower()
        for img in soup.select("img.gallery-img"):
            raw = str(img.get("src") or "").strip()
            alt = str(img.get("alt") or "").strip().lower()
            if not raw or not display_name or not alt.startswith(display_name):
                continue
            photo = urljoin("https://carros.com/", raw)
            p = _urlparse(photo)
            if (p.hostname or "").lower() not in {"carros.com", "www.carros.com"}:
                continue
            if p.scheme == "http":
                photo = urlunparse(p._replace(scheme="https"))
                p = _urlparse(photo)
            if p.scheme == "https":
                listing.photos = [photo]
                break
    if miles_match:
        try:
            amount = int(miles_match.group(1).replace(",", ""))
            unit = miles_match.group(2).lower()
        except (ValueError, IndexError):
            amount = None
            unit = None
        if amount is not None and 0 <= amount <= 2000000:
            listing.km = Field(value=round(amount * 1.609344) if unit != "km" else amount,
                               confidence="medium")


def parse_html(url: str, html: str) -> Listing:
    """Parse already-fetched HTML without additional outbound network requests."""
    listing = Listing(platform="unknown", url=url)
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

    _carroselsalvador_detail(html, listing)
    _experimental_listing_detail(html, listing)
    return listing
