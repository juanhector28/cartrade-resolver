"""Browser E2E for two exact Anuto SV individual ads, read-only staging."""
import asyncio,json
from pathlib import Path
from playwright.async_api import async_playwright

BASE="https://cartrade-paste-link-staging.onrender.com"
OUT=Path("/tmp/carly-anuto-browser")
CASES=[
 ("yaris","https://sv.anuto.app/ad/se-vende-toyota-yaris-automatico-0nPyz4dvggGHLtrN8nVx",2500,2008,135000,"yaris"),
 ("tacoma","https://sv.anuto.app/ad/toyota-tacoma-2021-Trgt028DJRkzLdjJO6d3",23500,2021,67000,"tacoma"),
]

async def main():
 OUT.mkdir(parents=True,exist_ok=True)
 report={"staging":BASE,"cases":[]}
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True,args=["--no-sandbox"])
  page=await browser.new_page(viewport={"width":1250,"height":900})
  await page.goto(BASE,wait_until="domcontentloaded",timeout=65000)
  for slug,url,price,year,km,token in CASES:
   row={"source":"sv.anuto.app","case":slug,"checks":{}}
   try:
    await page.locator("#url").fill(url)
    await page.locator("#send").click()
    await page.locator("#card").wait_for(state="visible",timeout=40000)
    row["title"]=await page.locator("#title").inner_text()
    row["price"]=await page.locator("#price").inner_text()
    row["km"]=await page.locator("#km").inner_text()
    row["checks"]["vehicle"]=token in row["title"].lower()
    row["checks"]["price"]=("$"+format(price,",")) in row["price"]
    row["checks"]["year"]=str(year) in await page.locator("#year").inner_text()
    row["checks"]["mileage"]=format(km,",") in row["km"]
    try:
     await page.wait_for_function("document.getElementById('photo').naturalWidth>0",timeout=16000)
     row["checks"]["photo_rendered"]=True
    except Exception:
     row["checks"]["photo_rendered"]=False
     row["photo_status"]=await page.locator("#photo-status").inner_text()
    await page.screenshot(path=str(OUT/(slug+".png")),full_page=True)
   except Exception as exc:
    row["error"]=type(exc).__name__+": "+str(exc)[:135]
    row["status"]=await page.locator("#status").inner_text()
   row["passed"]=len(row["checks"])==5 and all(row["checks"].values()) and not row.get("error")
   report["cases"].append(row)
   print(json.dumps(row,ensure_ascii=False),flush=True)
  await browser.close()
 report["passed"]=sum(x["passed"] for x in report["cases"])
 report["total"]=len(CASES)
 (OUT/"results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
 print(json.dumps({"passed":report["passed"],"total":report["total"]}),flush=True)
 if report["passed"]!=report["total"]:raise SystemExit(1)
if __name__=="__main__":
 asyncio.run(main())
