"""Inspect at most three exact public Excel Usados listing DOMs, with robots gate.

Reports HTML element shape, selected labels and image provenance, never seller
contacts, entire page HTML or downloaded image bytes. No redirects or retries.
"""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup

BASE="https://usados.excelautomotriz.com"
AGENT="CarTrade-Link-Diagnostic/0.1"
URLS=[
  "https://usados.excelautomotriz.com/autos-el-salvador/suzuki-celerio-p-81ce6/",
  "https://usados.excelautomotriz.com/autos-el-salvador/bmw-316-i-2014/",
  "https://usados.excelautomotriz.com/autos-el-salvador/suzuki-dzire-p-79aca/",
]
async def main():
 async with httpx.AsyncClient(timeout=16,follow_redirects=False,headers={"User-Agent":AGENT}) as c:
  robot=await c.get(BASE+"/robots.txt")
  result={"robots":robot.status_code}
  print(json.dumps(result),flush=True)
  if robot.status_code not in (200,404):return
  rp=RobotFileParser()
  if robot.status_code==200:rp.parse(robot.text.splitlines())
  for index,url in enumerate(URLS):
   if index:await asyncio.sleep(1)
   row={"url":url}
   if robot.status_code==200 and not rp.can_fetch(AGENT,url):
    row["status"]="robots_disallow";print(json.dumps(row),flush=True);continue
   try:
    r=await c.get(url)
    row["http"]=r.status_code
    if r.status_code!=200 or "html" not in r.headers.get("content-type","").lower() or len(r.content)>2000000:
     print(json.dumps(row),flush=True);continue
    soup=BeautifulSoup(r.text,"html.parser")
    row["title"]=soup.title.get_text(" ",strip=True)[:120] if soup.title else None
    row["h1"]=[{"text":h.get_text(" ",strip=True)[:130],"class":h.get("class"),"parent":h.parent.name,"parent_class":h.parent.get("class")} for h in soup.select("h1")[:3]]
    row["label_candidates"]=[]
    patterns=re.compile(r"^(?:Precio|Recorrido|Año|Marca\s*/\s*Modelo|Kilometraje|.*Kilometros)$",re.I)
    for el in soup.find_all(["h1","h2","h3","h4","span","strong","p","div","li"]):
     string=el.get_text(" ",strip=True)
     if not string or len(string)>90:continue
     if not patterns.search(string) and not re.match(r"^\$\s*[\d,]+",string):continue
     if el.find(["h1","h2","h3","h4","p","div","span","li"]):continue
     par=el.parent
     row["label_candidates"].append({"tag":el.name,"text":string[:80],"class":str(el.get("class") or "")[:95],
      "parent_tag":par.name,"parent_class":str(par.get("class") or "")[:95],
      "parent_text":par.get_text(" ",strip=True)[:150]})
     if len(row["label_candidates"])>=22:break
    row["images"]=[]
    for img in soup.select("img[src]")[:18]:
     row["images"].append({"src":str(img.get("src"))[:170],"alt":str(img.get("alt") or "")[:100],
      "class":str(img.get("class") or "")[:100],"parent":img.parent.name,
      "parent_class":str(img.parent.get("class") or "")[:70]})
    row["picture_count"]=len(soup.select("img[src]"))
    row["social_meta"]=[{"property":x.get("property") or x.get("name"),"value":str(x.get("content"))[:100]}
      for x in soup.select("meta[property],meta[name]") if
      "image" in str(x.get("property") or x.get("name")).lower()][:5]
    row["stripped_text_head"]=soup.get_text(" ",strip=True)[:600]
   except httpx.HTTPError as ex:
    row["exception"]=type(ex).__name__
   print(json.dumps(row,ensure_ascii=False),flush=True)
if __name__=="__main__":
 asyncio.run(main())
