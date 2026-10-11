"""Run one browser end-to-end test against isolated Carly staging."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

BASE = os.getenv("STAGING_URL", "https://cartrade-paste-link-staging.onrender.com")
URL = os.getenv("TEST_LISTING_URL") or "https://www.carroselsalvador.com/anuncios/kia-sportage-2006/"
IS_JULAJUPS = "julajups.sv/anuncio/" in URL
OUT = Path("/tmp/carly-staging-browser")


async def main():
    OUT.mkdir(exist_ok=True)
    report = {"base": BASE, "url": URL, "success": False,
              "checks": {}, "error": None}
    try:
        async with httpx.AsyncClient(timeout=55) as client:
            response = await client.get(BASE + "/health")
            report["checks"]["health_http_200"] = response.status_code == 200
            if response.status_code == 200:
                report["checks"]["staging_readonly"] = response.json().get("storage") is False
            api = await client.post(BASE + "/api/resolve", json={"url": URL})
            report["checks"]["api_http_200"] = api.status_code == 200
            if api.status_code != 200:
                report["api_failure_code"] = api.status_code
                report["api_response"] = api.text[:300]
                raise RuntimeError("Staging API did not resolve test vehicle")
            data = api.json()
            report["checks"]["correct_title"] = ("4runner" in data.get("title", "").lower().replace(" ", "").replace("-", "") or "4 runner" in data.get("title", "").lower()) if IS_JULAJUPS else "sportage" in data.get("title", "").lower()
            report["checks"]["correct_price"] = data.get("price_usd") == (27500 if IS_JULAJUPS else 5700)
            report["checks"]["correct_year"] = data.get("year") == (2019 if IS_JULAJUPS else 2006)
            report["checks"]["correct_mileage"] = (data.get("km") is None or isinstance(data.get("km"), (int, float))) if IS_JULAJUPS else data.get("km") == 160934
            report["checks"]["not_persisted"] = data.get("saved") is False
            report["checks"]["photo_url_present"] = bool(data.get("photos"))
        async with async_playwright() as browser_tool:
            browser = await browser_tool.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page(viewport={"width": 1250, "height": 900}, device_scale_factor=1)
            await page.goto(BASE, wait_until="domcontentloaded", timeout=75000)
            report["checks"]["form_present"] = await page.locator("#url").count() == 1
            await page.locator("#url").fill(URL)
            await page.locator("#send").click()
            await page.locator("#card").wait_for(state="visible", timeout=45000)
            report["checks"]["browser_price"] = ("$27,500" if IS_JULAJUPS else "$5,700") in (await page.locator("#price").inner_text())
            try:
                await page.wait_for_function(
                    "document.getElementById('photo').naturalWidth > 0", timeout=18000)
                report["checks"]["photo_loaded_in_browser"] = True
            except Exception:
                report["checks"]["photo_loaded_in_browser"] = False
                report["photo_status"] = await page.locator("#photo-status").inner_text()
            report["browser_title"] = await page.locator("#title").inner_text()
            await page.screenshot(path=str(OUT / "carly-paste-link.png"), full_page=True)
            await browser.close()
        report["success"] = all(report["checks"].values())
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)[:240]
    finally:
        (OUT / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False))
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
