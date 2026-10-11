"""One-time, bounded staging audit for three Atlas-observed SV listing URLs.

Does not scrape catalog pages, persist vehicle data, access production, download
photos, or bypass source access restrictions. Reference prices from the Atlas
census are historical and must be visually rechecked before certification.
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import httpx

BASE = "https://cartrade-paste-link-staging.onrender.com"
OUT = Path("/tmp/paste-link-wave2-audit.json")
CASES = [
    {"source":"Motora SV","url":"https://motorasv.com/cars/5122d37b-997d-478c-9b16-863b40dca5e4",
     "expected_year":2017,"atlas_price_reference":7200,"identity":["kia","forte"]},
    {"source":"Disaz Autos","url":"https://www.disazautos.com/product-page/kia-seltos-2023",
     "expected_year":2023,"atlas_price_reference":18900,"identity":["kia","seltos"]},
    {"source":"AutosPublicidad","url":"https://www.autospublicidad.com/sv/detalles?auto=toyota-tacoma&id=73",
     "expected_year":2020,"atlas_price_reference":23500,"identity":["toyota","tacoma"]},
]

async def main():
    report={"environment":"isolated Render staging","source":"Atlas SV PR 133 sample citations",
            "caveat":"Only three named vehicle URLs; Atlas prices are historical baselines",
            "samples":[]}
    try:
        async with httpx.AsyncClient(timeout=35,follow_redirects=False) as cli:
            health=await cli.get(BASE+"/health")
            report["health_http_status"]=health.status_code
            if health.status_code != 200:
                raise RuntimeError("staging health not 200")
            report["sources_enabled"]=health.json().get("sources_enabled")
            if report["sources_enabled"] != 7:
                raise RuntimeError("staging source registry not at seven")
            for case in CASES:
                row={"source":case["source"],"url":case["url"],"expected_year":case["expected_year"],
                     "atlas_price_reference":case["atlas_price_reference"],"result":"not_tested"}
                try:
                    r=await cli.post(BASE+"/api/resolve",json={"url":case["url"]})
                    row["http_status"]=r.status_code
                    data=r.json()
                    if r.status_code != 200:
                        row["result"]="blocked_or_failed"
                        row["reason"]=str(data.get("detail","unknown"))[:180]
                    else:
                        row["title"]=data.get("title")
                        row["price_usd"]=data.get("price_usd")
                        row["year"]=data.get("year")
                        row["km"]=data.get("km")
                        row["photo_count"]=len(data.get("photos") or [])
                        row["source_stage"]=data.get("source_stage")
                        row["checks"]={
                           "identity":all(v in str(row["title"]).lower() for v in case["identity"]),
                           "year":row["year"]==case["expected_year"],
                           "price_present":isinstance(row["price_usd"],(int,float)) and row["price_usd"]>0,
                           "km_present":isinstance(row["km"],(int,float)) and row["km"]>=0,
                           "photo_url_present":row["photo_count"]>0,
                           "read_only":data.get("saved") is False,
                        }
                        row["price_matches_atlas_reference"]=row["price_usd"]==case["atlas_price_reference"]
                        row["result"]="all_fields_returned" if all(row["checks"].values()) else "incomplete_fields"
                except (httpx.HTTPError,ValueError) as e:
                    row["result"]="request_exception"
                    row["reason"]=type(e).__name__
                report["samples"].append(row)
                await asyncio.sleep(1)
    except (httpx.HTTPError,RuntimeError) as e:
        report["failure"]=str(e)[:250]
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if report.get("failure") or any(row["result"]!="all_fields_returned" for row in report["samples"]) or len(report["samples"])!=len(CASES):
        raise SystemExit(1)

if __name__=="__main__":
    asyncio.run(main())
