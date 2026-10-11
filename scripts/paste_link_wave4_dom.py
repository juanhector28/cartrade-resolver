"""Inspect only vehicle-data markers in three publicly reachable candidate pages.

Three exact URLs and their robots files; no retries, image downloads, catalog
traversal or raw HTML persistence. Report safe structural evidence only.
"""
from __future__ import annotations
import asyncio
import json
import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup

AGENT="CarTrade-Link-Diagnostic/0.1"
SOURCES=[
  ("excel","https://usados.excelautomotriz.com/autos-el-salvador/suzuki-dzire-p-79aca/",["suzuki","dzire","13000"]),
  ("xautomarket","https://xautomarket.com/comprar/JC663762",["pathfinder","JC663762","precio"]),
  ("credipro","https://credipro.com.sv/stock/#vehicle-09209cf893fa62c3",["09209cf893fa62c3","KIA SOUL","11900"]),
]

async def main():
 async with httpx.AsyncClient(timeout=15,follow_redirects=False,headers={"User-Agent":AGENT}) as cli:
  for n,(source,url,terms) in enumerate(SOURCES):
   if n: await asyncio.sleep(1)
   p=urlparse(url)
   row={"source":source}
   try:
    resp=await cli.get(f"{p.scheme}://{p.netloc}/robots.txt")
    row["robots_http"]=resp.status_code
    if resp.status_code==200:
     robots=RobotFileParser();robots.parse(resp.text.splitlines())
     if not robots.can_fetch(AGENT,url):
      row["access"]="disallowed";print(json.dumps(row));continue
    elif resp.status_code!=404:
     row["access"]="not_verified";print(json.dumps(row));continue
    r=await cli.get(url)
    row["http"]=r.status_code
    if r.status_code!=200 or "html" not in r.headers.get("content-type","").lower() or len(r.content)>1500000:
     print(json.dumps(row));continue
    soup=BeautifulSoup(r.text,"html.parser")
    visible=soup.get_text(" ",strip=True)
    row["visible_text_length"]=len(visible)
    row["title"]=soup.title.get_text(" ",strip=True)[:100] if soup.title else None
    row["headers"]=[e.get_text(" ",strip=True)[:110] for e in soup.select("h1,h2,h3")[:10]]
    row["term_counts"]={term:{"html":len(re.findall(re.escape(term),r.text,re.I)),
            "visible":len(re.findall(re.escape(term),visible,re.I))} for term in terms}
    row["vehicle_id_present_as_element_id"]={
       term:bool(soup.find(id=re.compile(re.escape(term),re.I))) for term in terms if len(term)>9
    }
    row["data_attributes"]={}
    for token in terms:
     hit=soup.find(string=re.compile(re.escape(token),re.I))
     if hit:
      parent=hit.parent
      row["data_attributes"][token]={"tag":parent.name,"parent_class":str(parent.get("class") or "")[:90],
       "parent_id":str(parent.get("id") or "")[:90],
       "nearby_text":parent.get_text(" ",strip=True)[:125]}
    row["script_src"]=[urlparse(e.get("src","")).path[:105] for e in soup.select("script[src]")[:11]]
    row["embedded_json_tags"]=[e.get("type") for e in soup.select('script[type="application/json"],script[type="application/ld+json"]')[:6]]
    row["links_to_vehicle"]=[{"href":a.get("href","")[:90],"title":a.get_text(" ",strip=True)[:45]}
       for a in soup.select("a[href]") if "vehicle" in a.get("href","") or "stock" in a.get("href","")][:4]
   except httpx.HTTPError as ex:
    row["network_error"]=type(ex).__name__
   print(json.dumps(row,ensure_ascii=False),flush=True)

if __name__=="__main__":
 asyncio.run(main())
