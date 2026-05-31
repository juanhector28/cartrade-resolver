"""OLX resolver.

OLX uses Next.js and embeds the listing data in two places:
  1. <script id="__NEXT_DATA__" type="application/json"> — full props payload
  2. <script type="application/ld+json"> — Product/Vehicle JSON-LD

We use Playwright headless because OLX has bot detection on direct httpx
requests. With a real Chromium user-agent and a brief render, we get the
fully-hydrated HTML and can extract from either source.
"""
from __future__ import annotations
import json
import re
import asyncio
from typing import Optional
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from .base import Listing, Field
from .. import parsers


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def _fetch_html(url: str, timeout_ms: int = 18000) -> Optional[str]:
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True,
                                              args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            ctx = await browser.new_context(user_agent=USER_AGENT,
                                            locale="es-SV",
                                            viewport={"width": 1280, "height": 800})
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                # Brief wait for JS hydration
                try:
                    await page.wait_for_selector("script#__NEXT_DATA__", timeout=4000)
                except PWTimeout:
                    pass
                html = await page.content()
            finally:
                await browser.close()
            return html
    except Exception:
        return None


def _extract_next_data(html: str) -> Optional[dict]:
    m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _extract_jsonld(html: str) -> list[dict]:
    out = []
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                         html, re.DOTALL):
        try:
            d = json.loads(m.group(1).strip())
            if isinstance(d, list):
                out.extend(d)
            else:
                out.append(d)
        except json.JSONDecodeError:
            continue
    return out


def _meta(html: str, prop: str) -> Optional[str]:
    pat = re.compile(
        rf'<meta[^>]*(?:property|name)=["\']{re.escape(prop)}["\'][^>]*content=["\']([^"\']+)["\']',
        re.IGNORECASE)
    m = pat.search(html)
    return m.group(1) if m else None


async def resolve(url: str) -> Listing:
    listing = Listing(platform="olx", url=url)

    html = await _fetch_html(url)
    if not html:
        listing.errors.append("playwright fetch failed (possibly blocked or timeout)")
        return listing

    # ─── Open Graph fallback values (always extract) ──────────────
    og_title = _meta(html, "og:title") or ""
    og_image = _meta(html, "og:image") or ""
    og_desc = _meta(html, "og:description") or ""

    if og_title:
        listing.title = Field(value=og_title.strip(), confidence="high")
    if og_image:
        listing.photos.append(og_image)

    # ─── JSON-LD: best structured source ──────────────────────────
    for d in _extract_jsonld(html):
        t = d.get("@type", "")
        if not isinstance(t, str):
            continue
        if t in ("Product", "Vehicle", "Car"):
            if "name" in d and listing.title is None:
                listing.title = Field(value=str(d["name"])[:200], confidence="high")
            if "image" in d:
                imgs = d["image"] if isinstance(d["image"], list) else [d["image"]]
                for im in imgs:
                    if isinstance(im, str) and im not in listing.photos:
                        listing.photos.append(im)
            if "description" in d:
                listing.description = Field(value=str(d["description"])[:500], confidence="high")
            offer = d.get("offers") or {}
            if isinstance(offer, dict):
                if "price" in offer:
                    try:
                        p = int(float(offer["price"]))
                        if 100 <= p <= 1_000_000:
                            cur = (offer.get("priceCurrency") or "").upper()
                            # If price is in BRL, MXN, etc. we still report; frontend can convert
                            listing.price_usd = Field(
                                value=p, confidence="high" if cur == "USD" else "medium")
                    except (ValueError, TypeError):
                        pass

    # ─── __NEXT_DATA__: very rich, varies by OLX version ──────────
    nd = _extract_next_data(html)
    if nd:
        # Walk to find ad data — common paths:
        # props.pageProps.ad, props.pageProps.props.ad
        def find_ad(obj, depth=0):
            if depth > 6 or not isinstance(obj, dict):
                return None
            if any(k in obj for k in ("title", "price", "list_id")) and "category" in obj:
                return obj
            for v in obj.values():
                if isinstance(v, dict):
                    r = find_ad(v, depth + 1)
                    if r:
                        return r
                elif isinstance(v, list):
                    for it in v[:5]:
                        if isinstance(it, dict):
                            r = find_ad(it, depth + 1)
                            if r:
                                return r
            return None

        ad = find_ad(nd) or {}
        if isinstance(ad, dict):
            if "title" in ad and listing.title is None:
                listing.title = Field(value=str(ad["title"])[:200], confidence="high")
            if "price" in ad and listing.price_usd is None:
                # OLX BR returns "R$ 12.000" string; parse digits
                txt = str(ad["price"])
                pr = parsers.extract_price_usd(txt) or parsers.extract_year(txt)
                if pr:
                    listing.price_usd = Field(value=pr[0], confidence="medium")
            if "body" in ad and listing.description is None:
                listing.description = Field(value=str(ad["body"])[:500], confidence="high")
            if "images" in ad and isinstance(ad["images"], list):
                for it in ad["images"]:
                    u = it.get("original") if isinstance(it, dict) else it
                    if isinstance(u, str) and u not in listing.photos:
                        listing.photos.append(u)
            # OLX-specific properties
            props = ad.get("properties") or []
            for prop in props:
                if not isinstance(prop, dict):
                    continue
                name = (prop.get("name") or prop.get("label") or "").lower()
                value = prop.get("value") or prop.get("values") or ""
                if isinstance(value, list):
                    value = value[0] if value else ""
                value = str(value)
                if not value:
                    continue
                if "ano" in name or "year" in name:
                    yr = parsers.extract_year(value)
                    if yr:
                        listing.year = Field(value=yr[0], confidence="high")
                elif "km" in name or "kilometr" in name:
                    km = parsers.extract_km(value)
                    if km:
                        listing.km = Field(value=km[0], confidence="high")
                elif "marca" in name or "brand" in name:
                    listing.make = Field(value=value, confidence="high")
                elif "modelo" in name or "model" in name:
                    listing.model = Field(value=value, confidence="high")
                elif "cambio" in name or "transmis" in name:
                    listing.transmission = Field(value=value, confidence="high")
                elif "combustivel" in name or "fuel" in name or "combustible" in name:
                    listing.fuel = Field(value=value, confidence="high")
            # Location
            loc = ad.get("locations_resolved") or ad.get("location") or {}
            if isinstance(loc, dict):
                city = loc.get("city") or loc.get("ad_municipality_name") or loc.get("name")
                state = loc.get("state") or loc.get("ad_state_name")
                if city:
                    parts = [str(city)]
                    if state and str(state) != str(city):
                        parts.append(str(state))
                    listing.location = Field(value=", ".join(parts), confidence="high")
            seller = ad.get("user") or {}
            if isinstance(seller, dict) and seller.get("name"):
                listing.seller_name = Field(value=str(seller["name"]), confidence="high")

    # ─── Fallback from title text if structured data missed it ───
    title_text = (listing.title.value if listing.title else og_title) or ""
    haystack = title_text + " " + og_desc
    if listing.year is None:
        listing.year = parsers.to_field(parsers.extract_year(haystack))
    if listing.km is None:
        listing.km = parsers.to_field(parsers.extract_km(haystack))
    if listing.make is None:
        listing.make = parsers.to_field(parsers.extract_make(haystack))
    if listing.model is None and listing.make:
        listing.model = parsers.to_field(parsers.extract_model(haystack, listing.make.value))
    if listing.transmission is None:
        listing.transmission = parsers.to_field(parsers.extract_transmission(haystack))
    if listing.fuel is None:
        listing.fuel = parsers.to_field(parsers.extract_fuel(haystack))

    listing.photos = listing.photos[:12]
    return listing
