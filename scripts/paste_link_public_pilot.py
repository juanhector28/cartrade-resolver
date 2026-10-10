"""Single-public-page, non-publishing Paste Link diagnostic.

One robots check and at most one listing GET. No crawl, no retries,
no CAPTCHA/proxy bypass, no HTML or image persistence.
"""
from __future__ import annotations
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse

import httpx
from app.resolvers import fallback

URL = "https://www.carroselsalvador.com/anuncios/kia-sportage-2006/"
ROBOT_URL = "https://www.carroselsalvador.com/robots.txt"
OUTPUT = Path("/tmp/paste_link_single_public_pilot.json")


async def main() -> int:
    receipt = {"checked_at": datetime.now(timezone.utc).isoformat(),
               "url": URL, "mode": "noncommercial-single-page-diagnostic",
               "result": "not_tested", "verified": False}
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=False,
                                     headers={"User-Agent": "CarTrade-Link-Diagnostic/0.1"}) as client:
            robots = await client.get(ROBOT_URL)
            receipt["robots_status"] = robots.status_code
            if robots.status_code == 200:
                parser = RobotFileParser()
                parser.parse(robots.text.splitlines())
                if not parser.can_fetch("CarTrade-Link-Diagnostic", URL):
                    receipt["result"] = "robots_disallowed"
                    return write(receipt)
            elif robots.status_code != 404:
                receipt["result"] = "robots_unavailable"
                return write(receipt)
            response = await client.get(URL)
            receipt["http_status"] = response.status_code
            if response.status_code != 200:
                receipt["result"] = f"http_{response.status_code}"
                return write(receipt)
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" not in content_type or len(response.content) > 2_000_000:
                receipt["result"] = "unexpected_content_type_or_size"
                return write(receipt)
            # The generic resolver is tested against the exact HTML from
            # this public listing, without issuing a second HTTP request.
            listing = fallback.parse_html(URL, response.text)
            obj = listing.to_dict()
            v = lambda key: obj[key]["value"] if isinstance(obj.get(key), dict) else None
            receipt["observed"] = {
                "title": v("title"), "price_usd": v("price_usd"),
                "year": v("year"), "km": v("km"),
                "photo_count": len(obj["photos"]), "errors": obj["errors"]}
            receipt["checks"] = {
                "correct_title": "kia" in str(v("title")).lower() and "sportage" in str(v("title")).lower(),
                "correct_year": v("year") == 2006,
                "correct_asking_price": v("price_usd") == 5700,
                "photo_present": len(obj["photos"]) > 0}
            receipt["verified"] = all(receipt["checks"].values()) and not obj["errors"]
            receipt["result"] = "pass" if receipt["verified"] else "field_mismatch"
    except (httpx.HTTPError, ValueError, OSError) as exc:
        receipt["result"] = "request_failed"
        receipt["error_type"] = type(exc).__name__
    return write(receipt)


def write(receipt: dict) -> int:
    OUTPUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if receipt["verified"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
