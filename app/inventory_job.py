import asyncio
import json
import re
from datetime import datetime, timezone

import httpx
from selectolax.parser import HTMLParser


SEARCH_URL = "https://www.encuentra24.com/el-salvador-es/autos-usados"
RESOLVER_API = "https://cartrade-resolver.onrender.com/resolve-link"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def fetch_html(url: str) -> str:
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "es-SV,es;q=0.9"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def extract_listing_urls(html: str) -> list[str]:
    tree = HTMLParser(html)
    urls = set()

    for node in tree.css("a[href]"):
        href = node.attributes.get("href", "")

        if "/autos-usados/" not in href:
            continue

        if href.startswith("/"):
            href = "https://www.encuentra24.com" + href

        href = href.split("?")[0]

        # Keep likely individual listing pages
        if re.search(r"/\d+$", href):
            urls.add(href)

    return sorted(urls)


async def discover_urls(pages: int = 3) -> list[str]:
    all_urls = set()

    for page in range(1, pages + 1):
        page_url = f"{SEARCH_URL}?page={page}"
        print(f"Discovering page {page}: {page_url}")

        html = await fetch_html(page_url)
        urls = extract_listing_urls(html)

        print(f"Found {len(urls)} listing URLs on page {page}")
        all_urls.update(urls)

    return sorted(all_urls)


async def resolve_listing(client: httpx.AsyncClient, url: str) -> dict:
    response = await client.post(RESOLVER_API, json={"url": url})
    response.raise_for_status()
    return response.json()


async def main():
    urls = await discover_urls(pages=3)

    print(f"Total unique URLs discovered: {len(urls)}")

    results = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for i, url in enumerate(urls, start=1):
            print(f"[{i}/{len(urls)}] Resolving {url}")

            try:
                listing = await resolve_listing(client, url)
                listing["inventory_source"] = "encuentra24"
                listing["inventory_country"] = "sv"
                listing["inventory_scraped_at"] = datetime.now(timezone.utc).isoformat()
                results.append(listing)

            except Exception as e:
                print(f"ERROR resolving {url}: {e}")

            await asyncio.sleep(1)

    output_file = "inventory_sv_encuentra24.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(results)} listings to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
