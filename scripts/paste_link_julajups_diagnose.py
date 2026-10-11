"""Inspect two previously recorded Julajups vehicle URLs without storing HTML.

At most one robots.txt request and two public listing GETs. No retries,
image downloads, catalog crawling or persistent data collection.
"""
from __future__ import annotations

import asyncio
import json
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup

from app.resolvers.fallback import parse_html, _structured_price, _meta

BASE="https://www.julajups.sv"
URLS=[
 BASE+"/anuncio/subaru-impreza-rs-2006-awd-pxODLWUM9S",
 BASE+"/anuncio/subaru-impreza-rs-2006-awd-V9E5S7iCG1",
]
AGENT="CarTrade-Link-Diagnostic/0.1"

async def main():
  async with httpx.AsyncClient(timeout=12.0,follow_redirects=False,headers={"User-Agent":AGENT}) as cli:
    try:
      robot=await cli.get(BASE+"/robots.txt")
      print(json.dumps({"robots_status":robot.status_code}))
      if robot.status_code not in (200,404):
        return
      parser=RobotFileParser()
      if robot.status_code==200:
        parser.parse(robot.text.splitlines())
      for url in URLS:
        row={"url":url}
        if robot.status_code==200 and not parser.can_fetch(AGENT,url):
          row["result"]="robots_disallowed"
          print(json.dumps(row)); continue
        try:
          res=await cli.get(url)
          row["http_status"]=res.status_code
          row["content_type"]=res.headers.get("content-type","")
          if res.status_code==200 and "html" in row["content_type"] and len(res.content)<1500000:
            html=res.text
            soup=BeautifulSoup(html,"html.parser")
            listing=parse_html(url,html)
            row.update({
              "title_tag":soup.title.get_text(" ",strip=True)[:120] if soup.title else None,
              "og_title":_meta(html,"og:title"),
              "og_desc_exists":bool(_meta(html,"og:description")),
              "og_image_present":bool(_meta(html,"og:image")),
              "structured_price":_structured_price(html),
              "jsonld_types":[str(tag.get_text())[:100] for tag in soup.select('script[type="application/ld+json"]')[:2]],
              "other_price_meta":[{"key":m.get("itemprop") or m.get("property"),"content":str(m.get("content"))[:70]}
                                  for m in soup.select("meta[itemprop],meta[property]") if "price" in str(m).lower()][:6],
              "visible_price_strings":[t.strip()[:90] for t in soup.stripped_strings
                                       if "$" in t and len(t)<120][:4],
              "parsed_title":listing.title.value if listing.title else None,
              "parsed_price":listing.price_usd.value if listing.price_usd else None,
              "errors":listing.errors,
            })
        except httpx.HTTPError as exc:
          row["network_error"]=type(exc).__name__
        print(json.dumps(row,ensure_ascii=False),flush=True)
        await asyncio.sleep(1)

if __name__=="__main__":
  asyncio.run(main())
