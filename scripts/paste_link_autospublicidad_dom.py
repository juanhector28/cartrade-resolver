"""Bounded DOM diagnostic for one Atlas-cited AutosPublicidad vehicle."""
from __future__ import annotations
import asyncio
import json
import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup

URL="https://www.autospublicidad.com/sv/detalles?auto=toyota-tacoma&id=73"
AGENT="CarTrade-Link-Diagnostic/0.1"

async def main():
    result={"url":URL}
    async with httpx.AsyncClient(timeout=20,follow_redirects=False,headers={"User-Agent":AGENT}) as client:
        robots=await client.get("https://www.autospublicidad.com/robots.txt")
        result["robots_status"]=robots.status_code
        if robots.status_code == 200:
            rp=RobotFileParser(); rp.parse(robots.text.splitlines())
            if not rp.can_fetch(AGENT,URL):
                print(json.dumps({**result,"blocked":"robots disallowed"}));return
        elif robots.status_code != 404:
            print(json.dumps({**result,"blocked":"robots unavailable"}));return
        res=await client.get(URL)
        result["http_status"]=res.status_code
        if res.status_code!=200 or len(res.content)>2000000:
            print(json.dumps(result));return
        soup=BeautifulSoup(res.text,"html.parser")
        result["title"]=soup.title.get_text(" ",strip=True)[:160] if soup.title else None
        result["meta"]=[{"key":tag.get("property") or tag.get("name"),
                         "content":str(tag.get("content"))[:125]}
                        for tag in soup.select("meta[property],meta[name]")
                        if any(w in str(tag.get("property") or tag.get("name")).lower() for w in ["image","title","description"])][:16]
        result["image_tags"]=[]
        for image in soup.find_all("img"):
            attrs={k:str(image.get(k))[:170] for k in ("src","alt","srcset","data-src","data-original","loading","class") if image.get(k)}
            if attrs:result["image_tags"].append(attrs)
            if len(result["image_tags"])==18:break
        result["image_tag_count"]=len(soup.find_all("img"))
        result["css_background_samples"]=[tag.get("style")[:180] for tag in soup.select('[style*="background"]')[:8]]
        txt=soup.get_text(" ",strip=True)
        result["measurements"]=[]
        for pattern in [r"kilometraje",r"recorrido",r"millas",r"\bkm\b",r"\bmi\b",r"od[oó]metro",r"\d{1,3}(?:,\d{3})+"]:
            matches=list(re.finditer(pattern,txt,re.I))
            result["measurements"].append({"pattern":pattern,"count":len(matches),
                 "surroundings":[txt[max(0,m.start()-55):m.end()+95] for m in matches[:3]]})
        result["image_scripts"]=len(soup.select('script[type="application/ld+json"]'))
        result["content_head"]=txt[:520]
        print(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":
    asyncio.run(main())
