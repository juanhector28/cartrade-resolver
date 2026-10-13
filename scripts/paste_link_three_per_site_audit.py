"""One bounded expansion pass to three real vehicle examples per domain.

Uses GitHub-tracked fixed URLs, never catalog crawling, URLs generated from
templates, automatic retries, image downloads or production/inventory writes.
Previously tested cases stay cited separately. Source prices can change.
One POST per pending example; stop immediately on staging's 429 limit.
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import httpx

BASE="https://cartrade-paste-link-staging.onrender.com"
MANIFEST=Path("ops/paste_link_sv_qa_3_per_site.json")
OUTPUT=Path("/tmp/carly-sv-three-per-domain-audit.json")

async def main():
    matrix=json.loads(MANIFEST.read_text())
    pending=[(d["domain"],case) for d in matrix["domains"] for case in d["cases"]
             if case["status"]=="pending"]
    assert len(matrix["domains"])==11
    assert 1 <= len(pending) <= 12, "keep the live probe within staging throttle"
    results=[]
    async with httpx.AsyncClient(timeout=42,follow_redirects=False) as client:
        h=await client.get(BASE+"/health")
        assert h.status_code==200 and h.json().get("production") is False
        for index,(domain,c) in enumerate(pending):
            if index:await asyncio.sleep(1.25)
            row={"domain":domain,"url":c["url"],"reference_price":c["atlas_reference_price"],
                 "reference_year":c["expected_year"]}
            try:
                r=await client.post(BASE+"/api/resolve",json={"url":c["url"]})
                row["http_status"]=r.status_code
                data=r.json()
                if r.status_code==429:
                    row["result"]="rate_limited_stop"
                    row["reason"]=str(data.get("detail") or "")[:160]
                    results.append(row)
                    print(json.dumps(row,ensure_ascii=False),flush=True)
                    break
                if r.status_code!=200:
                    row["result"]="source_failure"
                    row["reason"]=str(data.get("detail") or "")[:190]
                else:
                    row["title"]=data.get("title")
                    row["price_usd"]=data.get("price_usd")
                    row["year"]=data.get("year")
                    row["km"]=data.get("km")
                    row["photo_count"]=len(data.get("photos") or [])
                    row["reference_price_same"]=data.get("price_usd")==c["atlas_reference_price"]
                    row["checks"]={
                        "title":bool(row["title"]),
                        "numeric_price":isinstance(row["price_usd"],(int,float)) and row["price_usd"]>0,
                        "year":row["year"]==c["expected_year"],
                        "photo_url":row["photo_count"]>0,
                        "read_only":data.get("saved") is False,
                        "source_host":data.get("source")==domain,
                    }
                    row["result"]="fields_complete" if all(row["checks"].values()) else "partial_fields"
            except (httpx.HTTPError,ValueError) as exc:
                row["result"]="request_error"
                row["error"]=type(exc).__name__
            results.append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
    report={"staging":BASE,"target_sites":len(matrix["domains"]),
        "new_pending_urls":len(pending),"checked":len(results),
        "passed":sum(r["result"]=="fields_complete" for r in results),
        "failed":sum(r["result"] not in ("fields_complete",) for r in results),
        "no_automatic_retries":True,
        "caveat":"Previously passed cases are documented separately. This is API field completeness, not image rendering, data accuracy independent of source or commercial permission.",
        "new_results":results}
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"checked":report["checked"],"passed":report["passed"],
                      "target":report["new_pending_urls"]}),flush=True)

if __name__=="__main__":
    asyncio.run(main())
