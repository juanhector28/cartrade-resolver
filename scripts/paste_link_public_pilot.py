"""Bounded, non-publishing diagnostic for 3 known public SV listings.

Exactly one robots check and at most 3 individual listing GETs; no crawling,
CAPTCHA bypass, retries, image download, Supabase access, or HTML persistence.
"""
from __future__ import annotations
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from app.resolvers import fallback

BASE = "https://www.carroselsalvador.com"
OUTPUT = Path("/tmp/paste_link_single_public_pilot.json")
CASES = [
    {"path": "/anuncios/kia-sportage-2006/", "title_tokens": ["kia", "sportage"],
     "price_usd": 5700, "year": 2006, "km": 160934},
    {"path": "/anuncios/honda-accord-2015/", "title_tokens": ["honda", "accord"],
     "price_usd": 8500, "year": 2015, "km": 209215},
    {"path": "/anuncios/ford-escape-2015-2/", "title_tokens": ["ford", "escape"],
     "price_usd": 10700, "year": 2015, "km": 236574},
]


def save(receipt: dict) -> int:
    OUTPUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if receipt.get("all_passed") else 1


async def main() -> int:
    receipt = {"checked_at": datetime.now(timezone.utc).isoformat(),
               "mode": "noncommercial-3-known-listing-diagnostic",
               "source": "carroselsalvador.com", "all_passed": False, "results": []}
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=False,
                                     headers={"User-Agent": "CarTrade-Link-Diagnostic/0.1"}) as client:
            robots = await client.get(BASE + "/robots.txt")
            receipt["robots_status"] = robots.status_code
            if robots.status_code == 200:
                parser = RobotFileParser()
                parser.parse(robots.text.splitlines())
                if any(not parser.can_fetch("CarTrade-Link-Diagnostic", BASE + c["path"])
                       for c in CASES):
                    receipt["result"] = "robots_disallowed"
                    return save(receipt)
            elif robots.status_code != 404:
                receipt["result"] = "robots_unavailable"
                return save(receipt)
            for i, case in enumerate(CASES):
                if i:
                    await asyncio.sleep(1)
                url = BASE + case["path"]
                row = {"url": url, "verified": False}
                response = await client.get(url)
                row["http_status"] = response.status_code
                if response.status_code != 200:
                    row["result"] = "http_error"
                    receipt["results"].append(row)
                    continue
                if "text/html" not in response.headers.get("content-type", "").lower() or len(response.content) > 2_000_000:
                    row["result"] = "invalid_body"
                    receipt["results"].append(row)
                    continue
                obj = fallback.parse_html(url, response.text).to_dict()
                def field(k):
                    return obj[k]["value"] if isinstance(obj.get(k), dict) else None
                title = str(field("title") or "").casefold()
                photos = obj["photos"]
                row["observed"] = {
                    "title": field("title"), "price_usd": field("price_usd"),
                    "year": field("year"), "km": field("km"), "photo_count": len(photos),
                    "errors": obj["errors"],
                }
                row["checks"] = {
                    "title": all(t in title for t in case["title_tokens"]),
                    "price_usd": field("price_usd") == case["price_usd"],
                    "year": field("year") == case["year"],
                    "km": field("km") == case["km"],
                    "photo_url": any(
                        isinstance(photo, str)
                        and urlparse(photo).scheme in ("https", "http")
                        and bool(urlparse(photo).hostname)
                        for photo in photos
                    ),
                }
                row["verified"] = all(row["checks"].values()) and not obj["errors"]
                row["result"] = "pass" if row["verified"] else "field_mismatch"
                receipt["results"].append(row)
            receipt["passed"] = sum(int(r["verified"]) for r in receipt["results"])
            receipt["all_passed"] = receipt["passed"] == len(CASES)
    except (httpx.HTTPError, ValueError, OSError) as exc:
        receipt["result"] = "request_failed"
        receipt["error_type"] = type(exc).__name__
    return save(receipt)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
