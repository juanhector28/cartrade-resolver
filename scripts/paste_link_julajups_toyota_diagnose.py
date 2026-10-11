"""Read-only diagnosis of one user-supplied Julajups Toyota listing.

One robots request, one individual listing GET, optionally one staging POST.
No catalog crawling, repeated requests, image downloads or HTML persistence.
"""
from __future__ import annotations

import asyncio
import json
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup
from app.resolvers.fallback import parse_html, _structured_price, _meta

URL = "https://www.julajups.sv/anuncio/toyota-4-runner-trd-2019-4x4-N3tSneYO52"
BASE = "https://www.julajups.sv"
STAGING = "https://cartrade-paste-link-staging.onrender.com"
AGENT = "CarTrade-Link-Diagnostic/0.1"


def summarize_jsonld(script):
    try:
        d = json.loads(script.string or script.get_text())
    except (TypeError, ValueError):
        return {"valid_json": False}
    blocks = d if isinstance(d, list) else [d]
    summary = []
    for item in blocks[:8]:
        if not isinstance(item, dict):
            continue
        offer = item.get("offers")
        offers = offer if isinstance(offer, list) else [offer]
        summary.append({
            "type": item.get("@type"), "name": str(item.get("name") or "")[:100],
            "price": item.get("price"), "currency": item.get("priceCurrency"),
            "offers": [
                {"type": x.get("@type"), "price": x.get("price"),
                 "currency": x.get("priceCurrency"), "availability": x.get("availability")}
                for x in offers[:3] if isinstance(x, dict)
            ],
        })
    return summary


async def main():
    receipt = {"url": URL}
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"User-Agent": AGENT}) as client:
        robots = await client.get(BASE + "/robots.txt")
        receipt["robots_http"] = robots.status_code
        if robots.status_code == 200:
            rp = RobotFileParser()
            rp.parse(robots.text.splitlines())
            if not rp.can_fetch(AGENT, URL):
                receipt["result"] = "robots_disallow"
                print(json.dumps(receipt, ensure_ascii=False), flush=True)
                return
        elif robots.status_code != 404:
            receipt["result"] = "robots_unavailable"
            print(json.dumps(receipt, ensure_ascii=False), flush=True)
            return
        response = await client.get(URL)
        receipt["source_http"] = response.status_code
        receipt["source_content_type"] = response.headers.get("content-type", "")
        if response.status_code == 200 and "html" in receipt["source_content_type"] and len(response.content) < 1500000:
            html = response.text
            soup = BeautifulSoup(html, "html.parser")
            listing = parse_html(URL, html)
            receipt["og"] = {key: _meta(html, key) for key in (
                "og:title", "og:description", "og:image", "product:price:amount",
                "product:price:currency",
            )}
            receipt["structured_price"] = _structured_price(html)
            receipt["jsonld"] = [summarize_jsonld(tag) for tag in soup.select('script[type="application/ld+json"]')[:5]]
            receipt["headings"] = [x.get_text(" ", strip=True)[:115] for x in soup.select("h1,h2")[:8]]
            receipt["price_content"] = [x.get_text(" ", strip=True)[:100] for x in
                soup.select('[class*="price"],[id*="price"],[class*="precio"],[id*="precio"]')[:8]]
            receipt["parsed"] = {
                "title": listing.title.value if listing.title else None,
                "price": listing.price_usd.value if listing.price_usd else None,
                "year": listing.year.value if listing.year else None,
                "km": listing.km.value if listing.km else None,
                "photos": len(listing.photos),
                "errors": listing.errors,
            }
        try:
            sr = await client.post(STAGING + "/api/resolve", json={"url": URL})
            receipt["staging_http"] = sr.status_code
            data = sr.json()
            receipt["staging"] = (
                {"title": data.get("title"), "price_usd": data.get("price_usd"),
                 "year": data.get("year"), "km": data.get("km"),
                 "photo_count": len(data.get("photos") or [])}
                if sr.status_code == 200 else {"detail": data.get("detail")}
            )
        except (httpx.HTTPError, ValueError) as exc:
            receipt["staging_error"] = type(exc).__name__
    print(json.dumps(receipt, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
