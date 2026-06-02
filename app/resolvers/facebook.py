"""Facebook Marketplace resolver.

Strategy: FB locks most data behind authentication and aggressively blocks
datacenter IPs. Rather than promise extraction we cannot reliably deliver,
we focus on what works: the og:image (foto principal) is publicly exposed
for link previews and works ~95% of the time.

What we promise:
- og:image (high confidence) — the main photo
- og:title (low confidence) — shown as "this is what FB says, confirm it"

What we no longer promise:
- Parsed price/year/km from title — too unreliable. Marked low confidence.
- All other fields — user fills manually.

Crucially: NO authenticated fetches. We do not bypass FB's login wall. That
violates Meta's ToS and exposes the business to legal risk.
"""
from __future__ import annotations
import re
import logging
import httpx
from .base import Listing, Field
from .. import parsers

log = logging.getLogger("resolver.facebook")

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
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT,
                                              "Accept-Language": "es-SV,es;q=0.9"}) as cli:
            r = await cli.get(url)
            if r.status_code >= 400:
                log.warning("facebook http %d for %s", r.status_code, url)
                listing.errors.append(f"http {r.status_code}")
                return listing
            html = r.text
    except httpx.TimeoutException as e:
        log.warning("facebook timeout: %s", url)
        listing.errors.append(f"timeout: {e!s}")
        return listing
    except httpx.HTTPError as e:
        log.warning("facebook http error: %s | url=%s", repr(e), url)
        listing.errors.append(f"http error: {repr(e)}")
        return listing

    og_title = _meta(html, "og:title") or ""
    og_image = _meta(html, "og:image") or ""
    og_desc = _meta(html, "og:description") or ""

    # Photo — what we actually promise
    if og_image:
        listing.photos.append(og_image)
        log.info("facebook photo extracted: %s", og_image[:80])

    # Title — show as low-confidence reference, NOT as truth
    if og_title:
        listing.title = Field(value=og_title.strip()[:200], confidence="low")

    # Description — same
    if og_desc:
        listing.description = Field(value=og_desc.strip()[:500], confidence="low")

    # Try to parse fields from title for the user as suggestions, but
    # mark ALL of them as low confidence so the UI shows "confirm this"
    haystack = (og_title + " " + og_desc).strip()
    if haystack:
        year_f = parsers.to_field(parsers.extract_year(haystack))
        if year_f: year_f.confidence = "low"; listing.year = year_f

        km_f = parsers.to_field(parsers.extract_km(haystack))
        if km_f: km_f.confidence = "low"; listing.km = km_f

        price_f = parsers.to_field(parsers.extract_price_usd(haystack))
        if price_f: price_f.confidence = "low"; listing.price_usd = price_f

        make_f = parsers.to_field(parsers.extract_make(haystack))
        if make_f:
            make_f.confidence = "low"; listing.make = make_f
            model_f = parsers.to_field(parsers.extract_model(haystack, make_f.value))
            if model_f: model_f.confidence = "low"; listing.model = model_f

    if not og_image and not og_title:
        listing.errors.append("Facebook devolvió datos vacíos (posible login-wall o bot detection)")
        log.warning("facebook empty response for %s", url)

    log.info("facebook result: photo=%s title_present=%s",
             "yes" if og_image else "no",
             "yes" if og_title else "no")

    return listing
