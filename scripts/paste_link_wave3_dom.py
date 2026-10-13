"""Inspect exactly one public listing per source, reporting metadata only."""
import asyncio
import json
import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

SOURCES=[
("carvimax","https://www.carvimax.com/hyundai-tucson/1570"),
("easycar","https://easycar.com.sv/car/109"),
("eurosport","https://www.eurosportautos.com/vehiculo/ford-bronco-sport-badlands-2024-4x4"),
("crediq","https://crediq.com/sv/product/chery-tiggo-2-pro-luxury-rojo-2026/"),
("julajups","https://www.julajups.sv/anuncio/subaru-impreza-rs-2006-awd-pxODLWUM9S"),
]
AGENT="CarTrade-Link-Diagnostic/0.1"
def samples(soup, pattern, limit=5):
    vals=[]
    for text in soup.find_all(string=True):
        if str(text).strip() and re.search(pattern,str(text),re.I):
            t=str(text)
            vals.append({"text":t[:125],"tag":getattr(text.parent,"name",None),
                         "class":str(text.parent.get("class") or "")[:85]})
            if len(vals)>=limit:break
    return vals

async def main():
  results=[]
  async with httpx.AsyncClient(timeout=15,follow_redirects=False,headers={"User-Agent":AGENT}) as c:
    for name,url in SOURCES:
      row={"source":name,"url":url,"status":"not_checked"}
      try:
        p=urlparse(url)
        robots=await c.get(f"{p.scheme}://{p.netloc}/robots.txt")
        row["robots_status"]=robots.status_code
        if robots.status_code==200:
            rp=RobotFileParser()
            rp.parse(robots.text.splitlines())
            row["robots_allows"]=rp.can_fetch(AGENT,url)
            if not row["robots_allows"]:
                row["status"]="robots_disallowed"
                print(json.dumps(row,ensure_ascii=False),flush=True)
                results.append(row)
                continue
        elif robots.status_code!=404:
            row["status"]="robots_unavailable"
            print(json.dumps(row,ensure_ascii=False),flush=True)
            results.append(row)
            continue
        r=await c.get(url)
        row["http_status"]=r.status_code
        row["redirect_to_host"]=urlparse(r.headers.get("location","")).hostname if 300<=r.status_code<400 else None
        if r.status_code!=200 or len(r.content)>1500000 or "html" not in r.headers.get("content-type",""):
            row["status"]="not_html_200"
            results.append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
            continue
        soup=BeautifulSoup(r.text,"html.parser")
        row["status"]="html_200"
        row["title_tag"]=soup.title.get_text(" ",strip=True)[:140] if soup.title else None
        row["headings"]=[{"tag":h.name,"text":h.get_text(" ",strip=True)[:130]} for h in soup.select("h1,h2,h3")[:12]]
        row["metas"]=[{"name":m.get("property") or m.get("name"),
                        "content":str(m.get("content") or "")[:170]}
                       for m in soup.select("meta[property],meta[name]")
                       if any(t in str(m.get("property") or m.get("name")).lower()
                           for t in ("title","image","price","description"))][:16]
        row["price_snippets"]=samples(soup,r"\$|USD|precio|price")[:7]
        row["mileage_snippets"]=samples(soup,r"milla|mileage|recorrido|kilometraje|\bkm\b|\bmi\b")[:7]
        row["images"]=[{"src":str(img.get("src") or "")[:130],"alt":str(img.get("alt") or "")[:85],
                        "class":str(img.get("class") or "")[:70]}
                       for img in soup.select("img[src]")[:9]]
        row["ld_json_count"]=len(soup.select('script[type="application/ld+json"]'))
        row["html_bytes"]=len(r.content)
      except httpx.HTTPError as exc:
        row["status"]="network_error";row["error_type"]=type(exc).__name__
      results.append(row)
      print(json.dumps(row,ensure_ascii=False),flush=True)
      await asyncio.sleep(1)
  print(json.dumps({"complete":len(results),"source_states":{r["source"]:r["status"] for r in results}}))

if __name__=="__main__":
  asyncio.run(main())
