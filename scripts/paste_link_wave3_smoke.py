"""One-time, five-site URL audit against isolated, read-only Carly staging.

Each case is a single Atlas-observed individual listing, not an inventory crawl.
Atlas reference prices are older observations, never the current truth.
No automatic retries, downloads of images, data persistence or production traffic.
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path

import httpx

BASE = "https://cartrade-paste-link-staging.onrender.com"
OUT = Path("/tmp/paste-link-wave3-audit.json")
CASES = [
    {"id": "carvimax", "url": "https://www.carvimax.com/hyundai-tucson/1570",
     "tokens": ["hyundai", "tucson"], "year": 2021, "atlas_reference_price": 19700},
    {"id": "easycar", "url": "https://easycar.com.sv/car/109",
     "tokens": ["hyundai", "accent"], "year": 2022, "atlas_reference_price": 11600},
    {"id": "eurosport", "url": "https://www.eurosportautos.com/vehiculo/ford-bronco-sport-badlands-2024-4x4",
     "tokens": ["ford", "bronco"], "year": 2024, "atlas_reference_price": 15300},
    {"id": "crediq", "url": "https://crediq.com/sv/product/chery-tiggo-2-pro-luxury-rojo-2026/",
     "tokens": ["chery", "tiggo"], "year": 2026, "atlas_reference_price": 21430},
    {"id": "julajups", "url": "https://www.julajups.sv/anuncio/subaru-impreza-rs-2006-awd-pxODLWUM9S",
     "tokens": ["subaru", "impreza"], "year": 2006, "atlas_reference_price": 4000},
]

async def main():
    report={"environment":BASE,"checked_count":0,"references":"Atlas SV PR #133 historical receipts",
            "results":[],"notes":"Field presence and historical price matching are NOT proof of current price."}
    async with httpx.AsyncClient(timeout=40,follow_redirects=False) as client:
        h=await client.get(BASE+"/health")
        report["health_status"]=h.status_code
        if h.status_code != 200:
            raise SystemExit("Staging health not 200")
        report["sources_enabled"]=h.json().get("sources_enabled")
        if report["sources_enabled"]!=12:
            raise SystemExit(f"Expected 12 stage sources, saw {report['sources_enabled']}")
        for i,c in enumerate(CASES):
            if i: await asyncio.sleep(1.1)
            row={"site":c["id"],"url":c["url"],"atlas_price_reference":c["atlas_reference_price"],
                 "expected_year":c["year"],"result":"not_tested"}
            try:
                r=await client.post(BASE+"/api/resolve",json={"url":c["url"]})
                row["http_status"]=r.status_code
                try: data=r.json()
                except ValueError: data={}
                if r.status_code!=200:
                    row["result"]="unavailable"
                    row["reason"]=str(data.get("detail") or r.text[:120])[:190]
                else:
                    row["observed"]={k:data.get(k) for k in ("title","price_usd","year","km","source_stage")}
                    row["observed"]["photo_count"]=len(data.get("photos") or [])
                    row["checks"]={
                        "identity":all(token in str(data.get("title") or "").casefold() for token in c["tokens"]),
                        "year":data.get("year")==c["year"],
                        "price_present":isinstance(data.get("price_usd"),(int,float)) and data["price_usd"]>0,
                        "photo_url_present":bool(data.get("photos")),
                        "km_present":isinstance(data.get("km"),(int,float)) and data["km"]>=0,
                        "not_saved":data.get("saved") is False,
                    }
                    row["price_matches_atlas_old_reference"]=data.get("price_usd")==c["atlas_reference_price"]
                    row["result"]="all_fields" if all(row["checks"].values()) else "partial_fields"
                report["checked_count"]+=1
            except (httpx.HTTPError,ValueError) as ex:
                row["result"]="request_error"
                row["reason"]=type(ex).__name__
            report["results"].append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"checked":len(report["results"]), "complete":sum(x["result"]=="all_fields" for x in report["results"])}),flush=True)

if __name__=="__main__":
    asyncio.run(main())
