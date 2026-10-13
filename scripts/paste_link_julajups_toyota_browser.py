"""Browser regression for the user's exact Julajups Toyota 4Runner link.

Two individual URLs only; no source crawling, backend caching or inventory writes.
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

BASE = "https://cartrade-paste-link-staging.onrender.com"
CASES = [
    {
        "name": "toyota_4runner_reported",
        "url": "https://www.julajups.sv/anuncio/toyota-4-runner-trd-2019-4x4-N3tSneYO52",
        "tokens": ["toyota", "4 runner"], "price": 27500, "year": 2019,
    },
    {
        "name": "subaru_previous_regression",
        "url": "https://www.julajups.sv/anuncio/subaru-impreza-rs-2006-awd-pxODLWUM9S",
        "tokens": ["subaru", "impreza"], "price": 4000, "year": 2006,
    },
]
OUTPUT = Path("/tmp/carly-julajups-toyota-browser")


async def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"staging": BASE, "passed": 0, "cases": []}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1200, "height": 900})
        await page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        for case in CASES:
            row = {"name": case["name"], "checks": {}}
            try:
                await page.locator("#url").fill(case["url"])
                await page.locator("#send").click()
                await page.locator("#card").wait_for(state="visible", timeout=45000)
                title = (await page.locator("#title").inner_text()).casefold()
                price = await page.locator("#price").inner_text()
                year = await page.locator("#year").inner_text()
                row["checks"]["correct_vehicle"] = all(x in title for x in case["tokens"])
                row["checks"]["exact_asking_price"] = "$" + format(case["price"], ",") in price
                row["checks"]["year"] = str(case["year"]) in year
                row["checks"]["original_url"] = await page.locator("#source").get_attribute("href") == case["url"]
                try:
                    await page.wait_for_function(
                        "document.getElementById('photo').naturalWidth > 0", timeout=17000
                    )
                    row["checks"]["photo_loaded"] = True
                except Exception:
                    row["checks"]["photo_loaded"] = False
                    row["photo_diagnostic"] = await page.locator("#photo-status").inner_text()
                row["price_shown"] = price
                await page.screenshot(path=str(OUTPUT / (case["name"]+".png")), full_page=True)
            except Exception as exc:
                row["error"] = type(exc).__name__ + ": " + str(exc)[:180]
                row["page_message"] = await page.locator("#status").inner_text()
            row["passed"] = len(row["checks"]) == 5 and all(row["checks"].values()) and not row.get("error")
            report["passed"] += int(row["passed"])
            report["cases"].append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        await browser.close()
    (OUTPUT / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if report["passed"] != len(CASES):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
