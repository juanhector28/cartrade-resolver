"""One-time public DOM inspection: no saved HTML, images or bulk requests."""
import asyncio
import json
import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup

CASES=[
 ("caragencia","https://caragencia.com/car-finder/2023-chevrolet-trailblazer"),
 ("carros.com","https://carros.com/car/b81740f31aee4629b3c8d1f7302a804f-p86776/"),
]
AGENT="CarTrade-Link-Diagnostic/0.1"

async def main():
    rows=[]
    async with httpx.AsyncClient(timeout=15,follow_redirects=False,headers={"User-Agent":AGENT}) as cli:
        for name,url in CASES:
            p=urlparse(url)
            row={"source":name}
            try:
                robot=await cli.get(f"{p.scheme}://{p.netloc}/robots.txt")
                row["robots_status"]=robot.status_code
                if robot.status_code==200:
                    parser=RobotFileParser()
                    parser.parse(robot.text.splitlines())
                    if not parser.can_fetch(AGENT,url):
                        row["outcome"]="robots_disallowed"
                        rows.append(row)
                        continue
                elif robot.status_code!=404:
                    row["outcome"]="robots_unavailable"
                    rows.append(row)
                    continue
                response=await cli.get(url)
                row["http_status"]=response.status_code
                if response.status_code!=200 or len(response.content)>2_000_000:
                    rows.append(row)
                    continue
                soup=BeautifulSoup(response.text,"html.parser")
                img=[]
                for tag in soup.find_all("img",limit=30):
                    fields={}
                    for key in ["src","data-src","data-original","data-lazy-src","alt","class","loading"]:
                        v=tag.get(key)
                        if v and key=="class":v=" ".join(v)
                        if v and key in {"src","data-src","data-original","data-lazy-src"}:
                            fields[key]={"host":urlparse(str(v)).hostname,"ends_with":str(v)[-36:]}
                        elif v:fields[key]=str(v)[:70]
                    if fields:img.append(fields)
                row["img_count"]=len(soup.find_all("img"))
                row["img_samples"]=img[:12]
                row["og_images"]=[{"content_host":urlparse(v.get("content","")).hostname,
                                  "property":v.get("property") or v.get("name")}
                                   for v in soup.select('meta[property*="image"],meta[name*="image"]')[:8]]
                text=soup.get_text(" ",strip=True)
                row["labels_found"]=[{"label":v,"context":text[max(0,m.start()-30):m.end()+75]}
                     for v in ["Odometer","Seller notes","Listing Price","Vehicle Details","Mileage"]
                     for m in list(re.finditer(re.escape(v),text,re.I))[:1]]
                rows.append(row)
            except httpx.HTTPError as ex:
                row["outcome"]=type(ex).__name__
                rows.append(row)
            await asyncio.sleep(1)
    print(json.dumps(rows,ensure_ascii=False,indent=2))

if __name__=="__main__":
    asyncio.run(main())
