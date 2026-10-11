"""Bounded preflight for two catalogue fragment ID candidates.

Only two static catalogue URLs, one robots check each, no query guessing,
catalogue traversal, images, stored HTML, retries or credentials.
Detect whether fragment maps to one source-anchored vehicle card, and whether
a current asking price is adjacent to the *identified* card.
"""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

AGENT = "CarTrade-Link-Diagnostic/0.1"
CASES = [
    {
        "source": "Autosale",
        "url": "https://autosale.com.sv/catalogo.php#vehicle-145",
    },
    {
        "source": "Credipro",
        "url": "https://credipro.com.sv/stock/#vehicle-09209cf893fa62c3",
    },
]
CURRENCY = re.compile(r"(?:US\s*)?\$\s*([0-9][0-9,.]{2,10})")

async def main():
    async with httpx.AsyncClient(timeout=15, follow_redirects=False,
                                 headers={"User-Agent": AGENT}) as client:
        for n, case in enumerate(CASES):
            if n:
                await asyncio.sleep(1.2)
            url = case["url"]
            target = urlparse(url)
            host = target.hostname
            record = {"source": case["source"], "fragment": target.fragment}
            try:
                robot = await client.get(f"https://{host}/robots.txt")
                record["robots_status"] = robot.status_code
                if robot.status_code == 200:
                    checker = RobotFileParser()
                    checker.parse(robot.text.splitlines())
                    if not checker.can_fetch(AGENT, url):
                        record["result"] = "robots_disallow"
                        print(json.dumps(record), flush=True)
                        continue
                elif robot.status_code != 404:
                    record["result"] = "robots_not_confirmed"
                    print(json.dumps(record), flush=True)
                    continue

                base_url = url.split("#", 1)[0]
                response = await client.get(base_url)
                record["http_status"] = response.status_code
                if response.status_code != 200 or len(response.content) > 1600000:
                    record["result"] = "no_usable_html"
                    print(json.dumps(record), flush=True)
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                matching_ids = soup.find_all(id=target.fragment)
                matching_names = soup.find_all(attrs={"name": target.fragment})
                matching_links = [
                    a for a in soup.find_all("a", href=True)
                    if a.get("href") == "#" + target.fragment
                ]
                record.update({
                    "fragment_found_by_dom_id": len(matching_ids),
                    "fragment_found_by_dom_name": len(matching_names),
                    "exact_fragment_links": len(matching_links),
                    "fragment_token_occurrences": response.text.lower().count(target.fragment.lower()),
                    "page_title": soup.title.get_text(" ", strip=True)[:90] if soup.title else None,
                    "candidate_card": None,
                })
                anchor = (matching_ids or matching_names)
                if len(anchor) == 1:
                    element = anchor[0]
                    parent = element.find_parent(["article", "li", "section", "div"])
                    if parent:
                        content = parent.get_text(" ", strip=True)
                        prices = CURRENCY.findall(content[:900])
                        record["candidate_card"] = {
                            "container_tag": parent.name,
                            "container_classes": list(parent.get("class") or [])[:5],
                            "text_chars": len(content),
                            "price_count": len(prices),
                            "candidate_price_unverified": prices[:3],
                        }
                if len(matching_ids) == 1 and record["candidate_card"] and record["candidate_card"]["price_count"] == 1:
                    record["result"] = "possible_unique_card_needs_three_examples"
                else:
                    record["result"] = "fragment_not_sufficient_for_listing_binding"
            except httpx.HTTPError as exc:
                record["result"] = "network_error"
                record["error_type"] = type(exc).__name__
            print(json.dumps(record, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    asyncio.run(main())
