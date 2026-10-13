"""Three isolated Carly browser checks: baseline + two wave-three readable sites.

Checks the *actual* rendered photo; unknown Julajups mileage stays unknown.
No writes to inventory, no bulk inventory crawling or retry loops.
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

BASE="https://cartrade-paste-link-staging.onrender.com"
OUT=Path("/tmp/carly-wave3-browser")
CASES=[
 {"site":"kia_regression","url":"https://www.carroselsalvador.com/anuncios/kia-sportage-2006/","price":5700,"year":2006,"km":160934},
 {"site":"carvimax","url":"https://www.carvimax.com/hyundai-tucson/1570","price":19700,"year":2021,"km":74746},
 {"site":"julajups","url":"https://www.julajups.sv/anuncio/subaru-impreza-rs-2006-awd-pxODLWUM9S","price":4000,"year":2006,"km":None},
]
async def main():
 OUT.mkdir(parents=True,exist_ok=True)
 report={"base":BASE,"results":[],"scope":"three specific individual user links, not domain-wide"}
 async with async_playwright() as pw:
  browser=await pw.chromium.launch(headless=True,args=["--no-sandbox"])
  page=await browser.new_page(viewport={"width":1250,"height":870})
  await page.goto(BASE,wait_until="domcontentloaded",timeout=70000)
  for case in CASES:
   result={"site":case["site"],"checks":{}}
   try:
    await page.locator("#url").fill(case["url"])
    await page.locator("#send").click()
    await page.locator("#card").wait_for(state="visible",timeout=35000)
    result["title"]=await page.locator("#title").inner_text()
    price=await page.locator("#price").inner_text()
    result["checks"]["price"]=" $"+format(case["price"],",") in " "+price
    result["checks"]["year"]=str(case["year"]) in await page.locator("#year").inner_text()
    mileage=await page.locator("#km").inner_text()
    result["checks"]["mileage"]=(format(case["km"],",") in mileage if case["km"] is not None
        else "no disponible" in mileage.lower())
    try:
     await page.wait_for_function("document.getElementById('photo').naturalWidth > 0",timeout=17000)
     result["checks"]["image_loaded"]=True
    except Exception:
     result["checks"]["image_loaded"]=False
     result["image_status"]=await page.locator("#photo-status").inner_text()
    await page.screenshot(path=str(OUT/(case["site"]+".png")),full_page=True)
   except Exception as exc:
    result["error"]=type(exc).__name__+": "+str(exc)[:160]
   result["passed"]=bool(result["checks"]) and all(result["checks"].values()) and not result.get("error")
   report["results"].append(result)
   print(json.dumps(result,ensure_ascii=False),flush=True)
  await browser.close()
 report["passed"]=sum(x["passed"] for x in report["results"])
 report["total"]=len(CASES)
 (OUT/"results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
 print(json.dumps({"passed":report["passed"],"total":report["total"]}))
 if report["passed"]!=report["total"]:raise SystemExit(1)
if __name__=="__main__":
 asyncio.run(main())
