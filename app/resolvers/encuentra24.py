"""Encuentra24 resolver.

Encuentra24 exposes Open Graph meta tags reliably and the body contains
structured key-value text like 'año2024', 'kilometraje5,790'. We don't need
a headless browser; httpx + selectolax is enough.

Price strategy: og:title is the most up-to-date source. When sellers drop
the price, the visible headline updates first, but og:description (which
contains the long-form 'Precio $X,XXX.XX') often lags with the old price.
So we prefer og:title for price, falling back to og:description.
"""
from __future__ import annotations
import re
import logging
import httpx
from selectolax.parser import HTMLParser
from .base import Listing, Field
from .. import parsers

log = logging.getLogger("resolver.encuentra24")

# Approximate FX — local units per 1 USD. These move slowly for these
# currencies; update here (or wire a live rate later) if precision matters.
# Used only to fill price_usd for cross-country comparison in Carly.
FX_PER_USD = {
    "USD": 1.0,
    "GTQ": 7.7,     # Guatemala · quetzal
    "HNL": 25.0,    # Honduras · lempira
    "NIO": 37.0,    # Nicaragua · córdoba
    "CRC": 515.0,   # Costa Rica · colón
    "DOP": 60.0,    # (por si aparece) Rep. Dominicana · peso
}

# Currency markers in priority order. Multi-char markers (RD$, C$, US$)
# MUST come before bare "$" so they win the match.
_MONEY_PATTERNS = [
    ("CRC", re.compile(r"₡\s*([\d.,]+)")),
    ("DOP", re.compile(r"RD\$\s*([\d.,]+)")),
    ("NIO", re.compile(r"C\$\s*([\d.,]+)")),
    ("USD", re.compile(r"(?:US\$|USD)\s*([\d.,]+)", re.IGNORECASE)),
    ("GTQ", re.compile(r"\b(?:Q|Qtz\.?|GTQ)\s*([\d.,]+)")),
    ("HNL", re.compile(r"\b(?:Lps?\.?|HNL)\s*([\d.,]+)")),
    ("USD", re.compile(r"\$\s*([\d.,]+)")),  # plain $ -> assume USD, last
]

# Loose sanity bounds per currency to reject junk matches.
_MONEY_BOUNDS = {
    "USD": (500, 200_000),
    "GTQ": (4_000, 2_000_000),
    "HNL": (12_000, 8_000_000),
    "NIO": (18_000, 12_000_000),
    "CRC": (250_000, 300_000_000),
    "DOP": (30_000, 30_000_000),
}


def _amount_to_int(raw: str) -> int | None:
    raw = raw.strip()
    raw = re.sub(r"[.,]\d{2}$", "", raw)        # drop trailing decimals (.00 / ,00)
    raw = raw.replace(",", "").replace(".", "")  # strip thousands separators
    try:
        return int(raw)
    except ValueError:
        return None


def parse_money(text: str) -> tuple[int | None, str | None]:
    """Detect the first plausible price + its currency in `text`.
    Returns (amount_in_local_units, currency_code) or (None, None)."""
    for currency, pat in _MONEY_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        amt = _amount_to_int(m.group(1))
        if amt is None:
            continue
        lo, hi = _MONEY_BOUNDS.get(currency, (1, 10**12))
        if lo <= amt <= hi:
            return amt, currency
    return None, None


def _set_price(listing: "Listing", amount: int, currency: str, confidence: str) -> None:
    """Store local price + currency, and fill price_usd (converted if needed)."""
    listing.currency = Field(value=currency, confidence=confidence)
    listing.price_local = Field(value=amount, confidence=confidence)
    if currency == "USD":
        listing.price_usd = Field(value=amount, confidence=confidence)
    else:
        rate = FX_PER_USD.get(currency)
        if rate:
            usd = round(amount / rate)
            # converted prices are estimates -> never "high"
            conf = "medium" if confidence == "high" else confidence
            listing.price_usd = Field(value=usd, confidence=conf)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def resolve(url: str) -> Listing:
    listing = Listing(platform="encuentra24", url=url)

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT,
                                              "Accept-Language": "es-SV,es;q=0.9"}) as cli:
            r = await cli.get(url)
            r.raise_for_status()
            html = r.text
    except httpx.TimeoutException as e:
        log.warning("encuentra24 timeout (>30s): %s", url)
        listing.errors.append(f"timeout: {e!s}")
        return listing
    except httpx.HTTPError as e:
        log.warning("encuentra24 http error: %s | url=%s", repr(e), url)
        listing.errors.append(f"http error: {repr(e)}")
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

    # Price extraction — Encuentra24 quirk:
    # When sellers drop the price, only the visible headline updates ($ X,XXX
    # shown next to the car title in the body). The og:description text often
    # lags with the old "Precio $X,XXX" from the description text. The og:title
    # rarely contains a price at all.
    #
    # Strategy (in order):
    # 1. Body text BEFORE "Descripción" section — this is the visible headline price.
    #    We slice the body to isolate it from the description (old price) and
    #    "Más anuncios" (other listings from same seller).
    # 2. og:title (in case it has a price)
    # 3. og:description "Precio $X,XXX.XX" pattern (last resort, may be stale)

    # 1. Body headline price — slice body to the section before "Descripción"
    headline_section = body_text
    desc_marker = re.search(r"Descripci[óo]n", body_text, re.IGNORECASE)
    if desc_marker:
        headline_section = body_text[:desc_marker.start()]
    # Also cut off "Detalles adicionales" if it's after "Descripción" wouldn't fire
    detail_marker = re.search(r"Detalles adicionales", headline_section, re.IGNORECASE)
    if detail_marker:
        # Keep what's after "Detalles" too since price often shown again there;
        # but cut off "Más anuncios" or "Otras publicaciones" from related listings
        pass
    rel_marker = re.search(r"M[áa]s anuncios|Otras publicaciones|Más vehículos", headline_section, re.IGNORECASE)
    if rel_marker:
        headline_section = headline_section[:rel_marker.start()]

    # Currency-aware extraction. parse_money recognizes ₡ Q L C$ RD$ $ and
    # returns (amount, currency); _set_price stores price_local + currency and
    # fills price_usd (converting non-USD via FX_PER_USD).
    # 1. Body headline (most current)
    if headline_section:
        amount, currency = parse_money(headline_section)
        if amount is not None:
            _set_price(listing, amount, currency, "high")
            log.info("price from body headline: %d %s", amount, currency)

    # 2. og:title fallback
    if listing.price_usd is None and og_title:
        amount, currency = parse_money(og_title)
        if amount is not None:
            _set_price(listing, amount, currency, "high")
            log.info("price from og:title: %d %s", amount, currency)

    # 3. og:description fallback (may be stale)
    if listing.price_usd is None and og_desc:
        amount, currency = parse_money(og_desc)
        if amount is not None:
            _set_price(listing, amount, currency, "medium")
            log.info("price from og:desc (may be stale): %d %s", amount, currency)

    # 4. Last resort: whole body (nearby listings make it less reliable)
    if listing.price_usd is None and body_text:
        amount, currency = parse_money(body_text)
        if amount is not None:
            _set_price(listing, amount, currency, "medium")

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

