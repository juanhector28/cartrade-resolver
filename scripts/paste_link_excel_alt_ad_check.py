"""Check three exact indexed Excel vehicle URLs for still-current public listing HTML.

One robots read, <=3 listing GETs, no retries/crawling/image downloads.
"""
import asyncio,json
from urllib.robotparser import RobotFileParser
import httpx
from app.resolvers.fallback import parse_html

BASE="https://usados.excelautomotriz.com"
AGENT="CarTrade-Link-Diagnostic/0.1"
PATHS=[
"/autos-el-salvador/foton-tunland-p-403d6/",
"/autos-el-salvador/kia-sportage-p-874162/",
"/autos-el-salvador/chevrolet-n400-p-792be/",
]
async def main():
 async with httpx.AsyncClient(timeout=17,follow_redirects=False,headers={"User-Agent":AGENT}) as cli:
  robots=await cli.get(BASE+"/robots.txt")
  print(json.dumps({"robots_http":robots.status_code}),flush=True)
  if robots.status_code not in (200,404):return
  rp=RobotFileParser()
  if robots.status_code==200:rp.parse(robots.text.splitlines())
  for i,path in enumerate(PATHS):
   if i:await asyncio.sleep(1.3)
   url=BASE+path
   row={"url":url}
   if robots.status_code==200 and not rp.can_fetch(AGENT,url):
    row["result"]="robots_disallowed";print(json.dumps(row));continue
   try:
    r=await cli.get(url)
    row["status"]=r.status_code
    if r.status_code==200 and "html" in r.headers.get("content-type","").lower() and len(r.content)<1600000:
     l=parse_html(url,r.text)
     row.update({"title":l.title.value if l.title else None,"price_usd":l.price_usd.value if l.price_usd else None,
       "year":l.year.value if l.year else None,"km":l.km.value if l.km else None,"photo_url_count":len(l.photos)})
   except httpx.HTTPError as exc:
    row["exception"]=type(exc).__name__
   print(json.dumps(row,ensure_ascii=False),flush=True)
if __name__=="__main__":asyncio.run(main())
