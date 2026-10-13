"""Nine read-only second-sample checks against isolated Carly staging."""
import asyncio
import json
import httpx
from pathlib import Path

BASE="https://cartrade-paste-link-staging.onrender.com"
CASES=[
("carroselsalvador.com","https://www.carroselsalvador.com/anuncios/scion-xb-2005-lujosos-san-salvador-3412/",5500,2005),
("tucarro.sv","https://tucarro.sv/hyundai-venue/c24ea1ec",11500,2020),
("caragencia.com","https://caragencia.com/es/car-finder/2020-honda-pilot-2",20000,2020),
("carros.com","https://carros.com/car/3039bc8f917d4f6d8453ed7e3568c2b5-p89767/",4500,2007),
("motorasv.com","https://motorasv.com/cars/d74b6a6a-628d-4abc-9cb4-5975e565d4ee",8400,2019),
("autospublicidad.com","https://www.autospublicidad.com/sv/detalles?auto=nissan-sentra&id=72",6700,2017),
("disazautos.com","https://www.disazautos.com/product-page/ford-bronco-sport-bandlands-2024-4x4",15300,2024),
("carvimax.com","https://www.carvimax.com/kia-soul/1563",6500,2013),
("julajups.sv","https://www.julajups.sv/anuncio/subaru-impreza-rs-2006-awd-V9E5S7iCG1",4000,2006),
]

async def main():
    results=[]
    async with httpx.AsyncClient(timeout=43,follow_redirects=False) as client:
        health=await client.get(BASE+"/health")
        if health.status_code!=200 or health.json().get("production") is not False:
            raise SystemExit("Staging unavailable: abort")
        for i,(domain,url,atlas_price,expected_year) in enumerate(CASES):
            if i: await asyncio.sleep(1.25)
            row={"domain":domain,"url":url,"old_atlas_price":atlas_price}
            try:
                response=await client.post(BASE+"/api/resolve",json={"url":url})
                row["http_status"]=response.status_code
                data=response.json()
                if response.status_code==200:
                    row.update({"title":data.get("title"),"price_usd":data.get("price_usd"),
                                "year":data.get("year"),"km":data.get("km"),
                                "photo_url_count":len(data.get("photos") or []),
                                "historical_price_matches":data.get("price_usd")==atlas_price})
                    row["checks"]={"title":bool(row["title"]),
                        "asking_price_present":isinstance(row["price_usd"],(int,float)) and row["price_usd"]>0,
                        "year":row["year"]==expected_year,
                        "photo_url":row["photo_url_count"]>0,
                        "not_saved":data.get("saved") is False}
                    row["result"]="fields_present" if all(row["checks"].values()) else "incomplete_fields"
                else:
                    row["result"]="source_failed"
                    row["reason"]=str(data.get("detail") or "")[:145]
            except (httpx.HTTPError,ValueError) as exc:
                row["result"]="request_error"
                row["exception"]=type(exc).__name__
            results.append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
    report={"staging":BASE,"checked":len(results),
        "fields_present":sum(x["result"]=="fields_present" for x in results),
        "note":"Atlas prices are historical; image URL presence is not browser loading proof.",
        "results":results}
    Path("/tmp/paste-link-nine-samples.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"checked":report["checked"],"fields_present":report["fields_present"]}),flush=True)

if __name__=="__main__":
    asyncio.run(main())
