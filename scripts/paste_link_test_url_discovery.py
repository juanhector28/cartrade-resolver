"""One-page-per-source listing URL discovery for QA; not bulk catalog scraping.

Read robots once per host; one permitted index page GET. Extract up to 8
same-host individual listing links. Never visit links, images or next pages.
"""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup
SOURCES=[
 ("TuCarro.sv","https://tucarro.sv/","tucarro.sv",r"^/[a-z0-9][a-z0-9-]*/[a-f0-9]{8}/?$"),
 ("Disaz Autos","https://www.disazautos.com/importados","disazautos.com",r"^/product-page/[a-z0-9][a-z0-9-]+/?$"),
 ("Carvimax","https://www.carvimax.com/","carvimax.com",r"^/[a-z0-9][a-z0-9-]+/[1-9][0-9]{0,6}/?$"),
 ("Excel Usados","https://usados.excelautomotriz.com/el-salvador/","usados.excelautomotriz.com",r"^/autos-el-salvador/[a-z0-9][a-z0-9-]+/?$"),
]
AGENT="CarTrade-Link-Diagnostic/0.1"
async def main():
 async with httpx.AsyncClient(timeout=18,follow_redirects=False,headers={"User-Agent":AGENT}) as client:
  for i,(name,base,host,pattern) in enumerate(SOURCES):
   if i:await asyncio.sleep(1.2)
   parsed=urlparse(base)
   row={"site":name,"index":base}
   try:
    robots=await client.get(parsed.scheme+"://"+parsed.netloc+"/robots.txt")
    row["robots"]=robots.status_code
    if robots.status_code==200:
     rp=RobotFileParser();rp.parse(robots.text.splitlines())
     if not rp.can_fetch(AGENT,base):
      row["access"]="disallowed";print(json.dumps(row));continue
    elif robots.status_code!=404:
     row["access"]="not_verified";print(json.dumps(row));continue
    response=await client.get(base)
    row["http"]=response.status_code
    if response.status_code!=200 or "html" not in response.headers.get("content-type","").lower() or len(response.content)>2400000:
     print(json.dumps(row));continue
    soup=BeautifulSoup(response.text,"html.parser")
    matched={}
    for a in soup.select("a[href]"):
     url=urljoin(base,a.get("href",""))
     p=urlparse(url)
     if p.scheme!="https" or (p.hostname or "").lower().removeprefix("www.")!=host or p.query or p.fragment:
      continue
     if re.fullmatch(pattern,p.path,re.I):
      if url not in matched:
       matched[url]=a.get_text(" ",strip=True)[:90]
     if len(matched)>=8:break
    row["vehicle_urls"]=[{"url":u,"label":t} for u,t in matched.items()]
    row["count"]=len(matched)
   except httpx.HTTPError as exc:
    row["error"]=type(exc).__name__
   print(json.dumps(row,ensure_ascii=False),flush=True)
if __name__=="__main__":
 asyncio.run(main())
