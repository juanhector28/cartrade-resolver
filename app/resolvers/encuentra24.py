"""Encuentra24 resolver.

Encuentra24 exposes Open Graph meta tags reliably and the body contains
structured key-value text like 'año2024', 'kilometraje5,790'. We don't need
a headless browser; httpx + selectolax is enough.

Price strategy: og:description ALWAYS contains "Precio $X,XXX.XX" — most reliable
source. Body text can have nearby car prices (related listings) so we prefer
og:description.
"""
from __future__ import annotations
import re
import logging
import httpx
from selectolax.parser import HTMLParser
from .base import Listing, Field
from .. import parsers

log = logging.getLogger("resolver.encuentra24")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def resolve(url: str) -> Listing:
    listing = Listing(platform="encuentra24", url=url)

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT,
                                              "Accept-Language": "es-SV,es;q=0.9"}) as cli:
            r = await cli.get(url)
            r.raise_for_status()
            html = r.text
    except httpx.HTTPError as e:
        log.warning("http fetch failed: %s", e)
        listing.errors.append(f"http error: {e!s}")
        return listing

    tree = HTMLParser(html)

    # ─── Open Graph meta tags ──────────────────────────────────────
    def meta(prop: str) -> str | None:
        n = tree.css_first(f'meta[property="{prop}"]') or tree.css_first(f'meta[name="{prop}"]')
        return n.attributes.get("content") if n else None

    og_title = meta("og:title") or ""
    og_image = meta("og:image") or ""
    og_desc = meta("og:description") or ""

    log.info("og:title=%s og:image=%s og:desc_len=%d", og_title[:80], "yes" if og_image else "no", len(og_desc))

    if og_title:
        listing.title = Field(value=og_title.split(" | ")[0].strip(), confidence="high")
    if og_image:
        listing.photos.append(og_image)

    # ─── Body text — Encuentra24 puts structured fields inline ────
    body_text = tree.body.text(separator=" ", strip=True) if tree.body else ""

    # Year: prefer the value in "año2024" pattern; else fallback to title scan
    m = re.search(r"año\s*([12]\d{3})", body_text, re.IGNORECASE)
    if m:
        try:
            y = int(m.group(1))
            if 1990 <= y <= 2027:
                listing.year = Field(value=y, confidence="high")
        except ValueError:
            pass
    if listing.year is None:
        listing.year = parsers.to_field(parsers.extract_year(og_title or body_text))

    # KM: "kilometraje5,790" pattern
    m = re.search(r"kilometraje[:\s]*([0-9][\d,\.]{1,8})", body_text, re.IGNORECASE)
    if m:
        raw = m.group(1).replace(",", "").replace(".", "")
        try:
            km = int(raw)
            if 0 < km < 1_000_000:
                listing.km = Field(value=km, confidence="high")
        except ValueError:
            pass
    if listing.km is None:
        listing.km = parsers.to_field(parsers.extract_km(og_title))

    # Fuel: "combustibleGasolina" pattern
    m = re.search(r"combustible\s*([A-Za-zÁÉÍÓÚáéíóúñÑ]+)", body_text)
    if m:
        fuel_raw = m.group(1).strip()
        listing.fuel = Field(value=fuel_raw, confidence="high")
    elif listing.fuel is None:
        listing.fuel = parsers.to_field(parsers.extract_fuel(og_title + " " + og_desc))

    # Transmission: "transmisiónAutomática" pattern
    m = re.search(r"transmisi[óo]n\s*([A-Za-zÁÉÍÓÚáéíóúñÑ]+)", body_text)
    if m:
        listing.transmission = Field(value=m.group(1).strip(), confidence="high")
    elif listing.transmission is None:
        listing.transmission = parsers.to_field(parsers.extract_transmission(og_title))

    # Price: og:description ALWAYS has "Precio $X,XXX.XX" — most reliable source.
    # Body text can pick up prices from related listings nearby on the page.
    if og_desc:
        # Look specifically for "Precio $X,XXX.XX" pattern in description
        m = re.search(r"Precio\s*\$\s*([0-9][\d,\.]{2,12})", og_desc, re.IGNORECASE)
        if m:
            raw = m.group(1)
            # Strip trailing decimal like .00 / .50
            raw = re.sub(r"\.\d{1,2}$", "", raw)
            raw = raw.replace(",", "").replace(".", "")
            try:
                price = int(raw)
                if 500 <= price <= 200_000:
                    listing.price_usd = Field(value=price, confidence="high")
                    log.info("price extracted from og:desc: $%d", price)
            except ValueError:
                pass
        # Fallback to generic dollar match in og_desc
        if listing.price_usd is None:
            listing.price_usd = parsers.to_field(parsers.extract_price_usd(og_desc))

    # Final fallback: body text (less reliable due to nearby listings)
    if listing.price_usd is None:
        listing.price_usd = parsers.to_field(parsers.extract_price_usd(body_text))
        if listing.price_usd:
            # Downgrade confidence — body text is less reliable
            listing.price_usd.confidence = "medium"

    # Make/model: from title (Encuentra24 puts these in title and as "Marca/Modelo" labels)
    listing.make = parsers.to_field(parsers.extract_make(og_title))
    if listing.make:
        listing.model = parsers.to_field(parsers.extract_model(og_title, listing.make.value))

    # Body fallback for make if title didn't match
    if listing.make is None:
        m = re.search(r"Marca\s+([A-Z][A-Za-z\-]+)", body_text)
        if m:
            listing.make = Field(value=m.group(1).strip(), confidence="high")
    if listing.model is None:
        m = re.search(r"Modelo\s+([A-Z][A-Za-z0-9\-\s]+?)(?=\s+(?:Tamaño|Año|Tracci|$))", body_text)
        if m:
            listing.model = Field(value=m.group(1).strip()[:30], confidence="high")

    # Location: in body, typically "City, City" or after "Ubicación"
    m = re.search(r"Ubicaci[óo]n\s+([A-ZÁÉÍÓÚ][A-Za-zÁÉÍÓÚáéíóúñÑ\s,]+?)(?=\s+(?:Marca|Tamaño|Modelo|$))",
                  body_text)
    if m:
        listing.location = Field(value=m.group(1).strip()[:50], confidence="high")

    # Description: under "## Descripción"
    if og_desc:
        listing.description = Field(value=og_desc.strip()[:500], confidence="high")

    # ─── More photos: scan body for photos.encuentra24.com URLs ───
    photo_pat = re.compile(r"https://photos\.encuentra24\.com/[^\s\"')]+")
    for url_ in set(photo_pat.findall(html)):
        if url_ not in listing.photos:
            listing.photos.append(url_)
    listing.photos = listing.photos[:12]

    log.info("result: name=%s price=%s km=%s photos=%d",
             listing.title.value if listing.title else None,
             listing.price_usd.value if listing.price_usd else None,
             listing.km.value if listing.km else None,
             len(listing.photos))

    return listing
