"""One-time, robots-aware Anuto ES pilot on two public vehicle listing URLs."""
import asyncio
import json
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from app.resolvers.fallback import parse_html

BASE="https://sv.anuto.app"
AGENT="CarTrade-Link-Diagnostic/0.1"
CASES=[
 ("toyota_yaris","https://sv.anuto.app/ad/se-vende-toyota-yaris-automatico-0nPyz4dvggGHLtrN8nVx",2500,2008),
 ("toyota_tacoma","https://sv.anuto.app/ad/toyota-tacoma-2021-Trgt028DJRkzLdjJO6d3",23500,2021),
]

async def main():
 async with httpx.AsyncClient(timeout=18,follow_redirects=False,headers={"User-Agent":AGENT}) as cli:
  robots=await cli.get(BASE+"/robots.txt")
  print(json.dumps({"robot_status":robots.status_code}),flush=True)
  if robots.status_code not in (200,404):
   return
  rp=RobotFileParser()
  if robots.status_code==200: rp.parse(robots.text.splitlines())
  for i,(case,url,old_price,expected_year) in enumerate(CASES):
   if i:await asyncio.sleep(1.3)
   row={"sample":case,"url":url}
   if robots.status_code==200 and not rp.can_fetch(AGENT,url):
    row["outcome"]="robots_disallowed"
    print(json.dumps(row),flush=True);continue
   try:
    r=await cli.get(url)
    row["http_status"]=r.status_code
    row["content_type"]=r.headers.get("content-type","")[:80]
    if r.status_code==200 and "html" in row["content_type"] and len(r.content)<1300000:
     html=r.text;soup=BeautifulSoup(html,"html.parser")
     listing=parse_html(url,html)
     row.update({
      "title_tag":soup.title.get_text(" ",strip=True)[:130] if soup.title else None,
      "headings":[h.get_text(" ",strip=True)[:100] for h in soup.select("h1,h2")[:5]],
      "og_title":bool(soup.select_one('meta[property="og:title"]')),
      "og_image":bool(soup.select_one('meta[property="og:image"]')),
      "jsonld_count":len(soup.select('script[type="application/ld+json"]')),
      "price_tag_samples":[p.get_text(" ",strip=True)[:55] for p in soup.select('[class*="price"],[class*="precio"]')[:5]],
      "source_image_count":len(soup.select('img[src]')),
      "parsed_title":listing.title.value if listing.title else None,
      "parsed_price":listing.price_usd.value if listing.price_usd else None,
      "parsed_year":listing.year.value if listing.year else None,
      "parsed_km":listing.km.value if listing.km else None,
      "parsed_photo_count":len(listing.photos),
      "price_matches_seen_public_listing":bool(listing.price_usd and listing.price_usd.value==old_price),
      "year_matches":bool(listing.year and listing.year.value==expected_year),
     })
     row["outcome"]="inspected"
    else:row["outcome"]="unavailable"
   except httpx.HTTPError as exc:
    row["outcome"]="network_error";row["type"]=type(exc).__name__
   print(json.dumps(row,ensure_ascii=False),flush=True)
if __name__=="__main__":
 asyncio.run(main())
