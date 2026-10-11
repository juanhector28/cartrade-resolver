"""Wave-four read-only source reconnaissance on five *named* Atlas SV URLs.

One robots lookup and at most one individual URL fetch per domain. No retries,
catalog crawling, API probing, image downloads, source HTML persistence or DB use.
Only structural signals get logged; historical prices are not certified.
"""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from app.resolvers.fallback import parse_html

AGENT = "CarTrade-Link-Diagnostic/0.1"
SAMPLES = [
    ("excel_usados",
     "https://usados.excelautomotriz.com/autos-el-salvador/suzuki-dzire-p-79aca/"),
    ("encuentra24",
     "https://www.encuentra24.com/el-salvador-es/autos-usados/en-venta-kia-forte-2023/33049654"),
    ("porsche_finder",
     "https://finder.porsche.com/sv/es-SV/details/porsche-cayenne-coupe-black-edition-nuevo-0OK0QN?condition=new&source=home"),
    ("xautomarket",
     "https://xautomarket.com/comprar/JC663762"),
    ("credipro_fragment",
     "https://credipro.com.sv/stock/#vehicle-09209cf893fa62c3"),
]


def examine(html: str, url: str):
    soup = BeautifulSoup(html, "html.parser")
    parsed = parse_html(url, html)
    types = []
    for tag in soup.select('script[type="application/ld+json"]')[:6]:
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
            values = data if isinstance(data, list) else [data]
            for item in values:
                if isinstance(item, dict):
                    types.append(str(item.get("@type"))[:35])
        except (TypeError, ValueError):
            types.append("invalid")
    title = soup.title.get_text(" ", strip=True)[:120] if soup.title else None
    prices = []
    for m in soup.select('meta[property*="price"],meta[itemprop*="price"]')[:8]:
        prices.append({"name":m.get("property") or m.get("itemprop"),
                       "value":str(m.get("content") or "")[:45]})
    return {
        "page_title":title,
        "page_h1_count":len(soup.select("h1")),
        "og_title":bool(soup.select_one('meta[property="og:title"]')),
        "og_image":bool(soup.select_one('meta[property="og:image"]')),
        "jsonld_types":types[:7],
        "price_meta":prices,
        "parsed_title":parsed.title.value if parsed.title else None,
        "parsed_price":parsed.price_usd.value if parsed.price_usd else None,
        "parsed_year":parsed.year.value if parsed.year else None,
        "parsed_km":parsed.km.value if parsed.km else None,
        "parsed_photo_count":len(parsed.photos),
        "html_bytes":len(html.encode()),
    }


async def main():
    report = []
    async with httpx.AsyncClient(timeout=13, follow_redirects=False,
                                 headers={"User-Agent":AGENT}) as cli:
        for i, (name,url) in enumerate(SAMPLES):
            if i: await asyncio.sleep(1.1)
            parsed = urlparse(url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            row = {"source":name,"sample_url":url,
                   "fragment_is_browser_only": bool(parsed.fragment)}
            try:
                robot = await cli.get(base+"/robots.txt")
                row["robots_status"] = robot.status_code
                if robot.status_code==200:
                    rp=RobotFileParser()
                    rp.parse(robot.text.splitlines())
                    row["robots_allowed"] = rp.can_fetch(AGENT,url)
                    if not row["robots_allowed"]:
                        row["outcome"]="robots_disallowed"
                        report.append(row); print(json.dumps(row,ensure_ascii=False),flush=True);continue
                elif robot.status_code!=404:
                    row["outcome"]="robots_unavailable"
                    report.append(row); print(json.dumps(row,ensure_ascii=False),flush=True);continue
                r=await cli.get(url)
                row["http_status"]=r.status_code
                row["redirect_host"]=urlparse(r.headers.get("location","")).hostname if 300<=r.status_code<400 else None
                row["content_type"]=r.headers.get("content-type","")[:75]
                if r.status_code == 200 and "html" in row["content_type"].lower() and len(r.content)<1800000:
                    row["signals"]=examine(r.text,url)
                    row["outcome"]="html_inspected"
                else:
                    row["outcome"]="no_public_detail_html"
            except (httpx.HTTPError, ValueError) as exc:
                row["outcome"]="network_error"
                row["error_type"]=type(exc).__name__
            report.append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
    print(json.dumps({"domains_checked":len(report),"html_inspected":sum(x["outcome"]=="html_inspected" for x in report)}))

if __name__=="__main__":
    asyncio.run(main())
