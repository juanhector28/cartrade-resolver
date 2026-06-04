import asyncio
import re
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

BASE = "https://crautos.com/autosusados/"
INDEX_URL = urljoin(BASE, "index.cfm")
SEARCH_URL = urljoin(BASE, "searchresults.cfm")
ID_RE = re.compile(r"cardetail\.cfm\?c=(\d+)")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "es-CR,es;q=0.9",
    "Referer": BASE,
}


def extract_ids(html: str) -> list[str]:
    return ID_RE.findall(html or "")


def find_next_url(html: str, current_url: str) -> str | None:
    tree = HTMLParser(html or "")

    candidates = []

    for a in tree.css("a[href]"):
        href = a.attributes.get("href", "")
        text = (a.text() or "").strip().lower()

        if "searchresults.cfm" in href:
            candidates.append(urljoin(current_url, href))

        if text in {"siguiente", ">", ">>"}:
            href = a.attributes.get("href")
            if href:
                candidates.append(urljoin(current_url, href))

    # dedupe
    candidates = list(dict.fromkeys(candidates))

    print(f"[crautos] candidatos next: {candidates[-5:]}")

    return candidates[-1] if candidates else None


async def discover_crautos(limit: int | None = None, max_pages: int = 400, delay: float = 1.0):
    seen = {}

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=30,
        headers=HEADERS,
    ) as client:
        # 1) Crear sesión/cookies
        first = await client.get(INDEX_URL)

        # 2) Empezar desde index porque sabemos que devuelve IDs
        url = str(first.url)

        for page_no in range(1, max_pages + 1):
            if page_no == 1:
                r = first
            else:
                r = await client.get(url, headers={**HEADERS, "Referer": url})

            html = r.text or ""
            ids = extract_ids(html)

            nuevos = 0
            for cid in ids:
                if cid not in seen:
                    seen[cid] = urljoin(BASE, f"cardetail.cfm?c={cid}")
                    nuevos += 1

            print(
                f"[crautos] pág {page_no} ({str(r.url)}): "
                f"+{nuevos} nuevos, total {len(seen)}"
            )

            if limit and len(seen) >= limit:
                break

            next_url = find_next_url(html, str(r.url))

            if not next_url or next_url == url:
                print("[crautos] no hay enlace siguiente, fin")
                break

            url = next_url

            if nuevos == 0 and page_no > 1:
                print("[crautos] página sin IDs nuevos, fin")
                break

            await asyncio.sleep(delay)

    items = list(seen.items())
    return items[:limit] if limit else items


if __name__ == "__main__":
    async def _main():
        res = await discover_crautos(limit=150, delay=1.0)
        print(f"\nDescubiertos: {len(res)}")
        for cid, url in res[:10]:
            print(cid, url)

    asyncio.run(_main())
