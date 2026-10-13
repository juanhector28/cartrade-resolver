"""One-time staging validation: health, source registry, two individual vehicle URLs.

No direct bulk queries, no database writes, no follow-on browsing of external sites.
"""
from __future__ import annotations
import asyncio
import json
import httpx

BASE="https://cartrade-paste-link-staging.onrender.com"
CASES=[
    {"id":"carroselsalvador","url":"https://www.carroselsalvador.com/anuncios/kia-sportage-2006/","price":5700,"year":2006,"km":160934},
    {"id":"tucarro","url":"https://tucarro.sv/ford-expedition/63f2c0e8","price":16500,"year":2018,"km":300000},
    {"id":"caragencia","url":"https://caragencia.com/car-finder/2023-chevrolet-trailblazer","price":13900,"year":2023,"km":65983},
    {"id":"carros.com","url":"https://carros.com/car/b81740f31aee4629b3c8d1f7302a804f-p86776/","price":9500,"year":2015,"km":125837},
]

async def main():
    report={"source":"Carly staging","version":"multisite","results":[]}
    async with httpx.AsyncClient(timeout=38, follow_redirects=False) as cli:
        for path in ("/health","/api/sources"):
            response=await cli.get(BASE+path)
            report[path]={"status":response.status_code,"data":response.json() if response.status_code==200 else response.text[:140]}
        for case in CASES:
            row={"id":case["id"],"url":case["url"]}
            try:
                res=await cli.post(BASE+"/api/resolve",json={"url":case["url"]})
                row["status"]=res.status_code
                data=res.json()
                if res.status_code==200:
                    row["title"]=data.get("title")
                    row["price_usd"]=data.get("price_usd")
                    row["year"]=data.get("year")
                    row["km"]=data.get("km")
                    row["photo_count"]=len(data.get("photos") or [])
                    row["source_stage"]=data.get("source_stage")
                    row["verified_fields"]=bool(
                        data.get("title") and data.get("price_usd")==case["price"]
                        and data.get("year")==case["year"] and data.get("km")==case["km"] and data.get("photos")
                        and data.get("saved") is False
                    )
                else:
                    row["reason"]=str(data.get("detail",data))[:190]
            except (httpx.RequestError,ValueError) as ex:
                row["exception"]=type(ex).__name__
            report["results"].append(row)
            await asyncio.sleep(1)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    with open("/tmp/carly-multisite-staging-report.json","w") as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
    # Keep exploratory-site outcomes informational but do not obscure established Kia regression.
    assert report["/health"]["status"]==200
    assert report["/api/sources"]["status"]==200
    assert len(report["/api/sources"]["data"]["sources"]) >= 8
    assert all(row.get("verified_fields") for row in report["results"]), (
        "One or more experimental source field checks remain incomplete")

if __name__=="__main__":
    asyncio.run(main())
