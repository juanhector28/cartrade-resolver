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


def extract_listing_headline_price(text: str, title: str = "") -> tuple[int | None, str | None]:
    """Find the CURRENT price in the vehicle headline, not a previous price.

    Encuentra24 can show a crossed-out price followed by a discounted price,
    e.g. "$43,182 $38,000 -12%". Taking the first money value is wrong.
    Restrict extraction to the section near the vehicle heading and before
    specification labels. Do not mine seller descriptions or related listings.
    """
    if not text:
        return None, None
    section = text
    if title:
        # The OG title may include suffixes and differ from rendered whitespace.
        short_title = title.split(" | ")[0].strip()
        at = section.casefold().find(short_title.casefold())
        if at >= 0:
            section = section[at + len(short_title):]
    # Specification labels ordinarily follow the listing's displayed price.
    boundary = re.search(
        r"\b(?:Año|Ano|Kilometraje|Combustible|Transmisi[oó]n|"
        r"Enviar consulta|Descripción|Detalles adicionales)\b",
        section[:650], re.IGNORECASE)
    if not boundary:
        return None, None
    section = section[:boundary.start()]
    # Stay close to the heading. This avoids header navigation and other ads.
    section = section[-320:]
    # Collect every plausible amount IN DOCUMENT ORDER, regardless of currency.
    candidates = []
    for currency, pattern in _MONEY_PATTERNS:
        for match in pattern.finditer(section):
            amount = _amount_to_int(match.group(1))
            lo, hi = _MONEY_BOUNDS[currency]
            if amount is not None and lo <= amount <= hi:
                candidates.append((match.start(), match.end(), amount, currency))
    if not candidates:
        return None, None
    # Suppress overlapping currency matches such as US$38,000 and $38,000.
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    unique = []
    for candidate in candidates:
        if not any(candidate[0] < previous[1] and candidate[1] > previous[0] for previous in unique):
            unique.append(candidate)
    # The sale price follows the struck-through original price.
    _, _, amount, currency = unique[-1]
    return amount, currency


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

async def _fetch_with_browser(url: str) -> str | None:
    """Fallback to a normal Chromium page load when plain HTTP is blocked.

    No authentication, CAPTCHA circumvention, stealth plugins, or proxy
    rotation. Only read publicly served listing HTML.
    """
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                page = await browser.new_page(
                    locale="es-SV", user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 900})
                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=17000)
                    if response is None or response.status >= 400:
                        log.warning("encuentra24 browser access denied: status=%s url=%s",
                                    response.status if response else None, url)
                        return None
                    await page.wait_for_timeout(750)
                    html = await page.content()
                    return html if "og:title" in html.lower() else None
                finally:
                    await page.close()
            finally:
                await browser.close()
    except Exception as exc:
        log.warning("encuentra24 browser fallback unavailable: %s", exc)
        return None


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def resolve(url: str) -> Listing:
    listing = Listing(platform="encuentra24", url=url)

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False,
                                     headers={"User-Agent": USER_AGENT,
                                              "Accept-Language": "es-SV,es;q=0.9"}) as cli:
            r = await cli.get(url)
            if 300 <= r.status_code < 400:
                listing.errors.append("redirect requires independent source review")
                return listing
            r.raise_for_status()
            html = r.text
    except httpx.TimeoutException as e:
        log.warning("encuentra24 timeout (>30s): %s", url)
        listing.errors.append(f"timeout: {e!s}")
        return listing
    except httpx.HTTPStatusError as e:
        if e.response.status_code not in (403, 429):
            listing.errors.append(f"http error: {repr(e)}")
            return listing
        log.info("encuentra24 direct HTTP blocked, attempting browser: %s", url)
        html = await _fetch_with_browser(url)
        if html is None:
            listing.errors.append(f"source access denied: HTTP {e.response.status_code}")
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

    # Price extraction: current listing headline only. Old prices appear first
    # when a discount is displayed; OG descriptions can be stale.
    amount, currency = extract_listing_headline_price(body_text, og_title)
    if amount is not None:
        _set_price(listing, amount, currency, "high")
        log.info("current price from listing headline: %d %s", amount, currency)
    elif og_title:
        # OG title is sometimes current, but do not trust the historical OG
        # description or unrelated body amounts as a current asking price.
        amount, currency = parse_money(og_title)
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

