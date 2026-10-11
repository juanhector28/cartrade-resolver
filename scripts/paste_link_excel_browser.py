"""Excel Usados browser E2E: one verified individual listing, no source catalog crawl."""
from __future__ import annotations
import asyncio,json
from pathlib import Path
from playwright.async_api import async_playwright

BASE="https://cartrade-paste-link-staging.onrender.com"
URL="https://usados.excelautomotriz.com/autos-el-salvador/suzuki-dzire-p-79aca/"
OUT=Path("/tmp/carly-excel-usados-browser")

async def main():
 OUT.mkdir(parents=True,exist_ok=True)
 result={"domain":"usados.excelautomotriz.com","url":URL,"checks":{}}
 async with async_playwright() as browser_api:
  browser=await browser_api.chromium.launch(headless=True,args=["--no-sandbox"])
  page=await browser.new_page(viewport={"width":1270,"height":920})
  await page.goto(BASE,wait_until="domcontentloaded",timeout=65000)
  await page.locator("#url").fill(URL)
  await page.locator("#send").click()
  try:
   await page.locator("#card").wait_for(state="visible",timeout=43000)
   title=await page.locator("#title").inner_text()
   price=await page.locator("#price").inner_text()
   year=await page.locator("#year").inner_text()
   km=await page.locator("#km").inner_text()
   result["checks"]={
     "vehicle":"suzuki" in title.lower() and "dzire" in title.lower(),
     "asking_price":"$13,000" in price,
     "year":"2025" in year,
     "odometer":"48,109" in km,
     "source_url":await page.locator("#source").get_attribute("href")==URL,
   }
   try:
    await page.wait_for_function("document.getElementById('photo').naturalWidth > 0",timeout=16000)
    result["checks"]["real_photo_rendered"]=True
   except Exception:
    result["checks"]["real_photo_rendered"]=False
    result["photo_status"]=await page.locator("#photo-status").inner_text()
   await page.screenshot(path=str(OUT/"excel-dzire.png"),full_page=True)
  except Exception as exc:
   result["error"]=type(exc).__name__+": "+str(exc)[:200]
   result["message"]=await page.locator("#status").inner_text()
  await browser.close()
 result["passed"]=len(result["checks"])==6 and all(result["checks"].values()) and not result.get("error")
 (OUT/"results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
 print(json.dumps(result,ensure_ascii=False),flush=True)
 if not result["passed"]:raise SystemExit(1)
if __name__=="__main__":
 asyncio.run(main())
