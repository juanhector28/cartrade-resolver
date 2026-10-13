"""Two exact stage regression URLs, no retries and stop if throttled."""
from __future__ import annotations
import asyncio,json
import httpx
from pathlib import Path
BASE="https://cartrade-paste-link-staging.onrender.com"
CASES=[
 ("carros.com", "https://carros.com/car/d8dc08898a3c4d1c9817268b42007df9-p89539/",6000,1980,1300),
 ("usados.excelautomotriz.com","https://usados.excelautomotriz.com/autos-el-salvador/kia-sportage-p-874162/",20900,2019,118362),
]
async def main():
    results=[]
    async with httpx.AsyncClient(timeout=35,follow_redirects=False) as c:
        h=await c.get(BASE+"/health")
        if h.status_code!=200 or h.json().get("production") is not False:
            raise SystemExit("staging not ready")
        for i,(domain,url,price,year,km) in enumerate(CASES):
            if i:await asyncio.sleep(1.5)
            row={"domain":domain,"url":url}
            try:
                res=await c.post(BASE+"/api/resolve",json={"url":url})
                row["http"]=res.status_code
                data=res.json()
                if res.status_code==429:
                    row["status"]="throttled_stop"
                    results.append(row)
                    print(json.dumps(row));break
                if res.status_code==200:
                    row.update({"title":data.get("title"),"price_usd":data.get("price_usd"),
                        "year":data.get("year"),"km":data.get("km"),"photo_count":len(data.get("photos") or [])})
                    row["checks"]={"price":row["price_usd"]==price,"year":row["year"]==year,
                        "km":row["km"]==km,"photo_url":row["photo_count"]>0,
                        "readonly":data.get("saved") is False}
                    row["status"]="pass" if all(row["checks"].values()) else "fail"
                else:
                    row["status"]="unavailable"
                    row["detail"]=str(data.get("detail") or "")[:160]
            except (httpx.HTTPError,ValueError) as ex:
                row["status"]="request_error"
                row["exception"]=type(ex).__name__
            results.append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
    Path("/tmp/carly-two-final-cases.json").write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n")
    assert len(results)==2 and all(x["status"]=="pass" for x in results)
if __name__=="__main__":asyncio.run(main())
