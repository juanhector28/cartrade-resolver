"""Bounded, browser-level seven-source Carly staging validation. No inventory writes."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "https://cartrade-paste-link-staging.onrender.com"
CASES = [
    ("carroselsalvador", "https://www.carroselsalvador.com/anuncios/kia-sportage-2006/", 5700),
    ("tucarro", "https://tucarro.sv/ford-expedition/63f2c0e8", 16500),
    ("caragencia", "https://caragencia.com/car-finder/2023-chevrolet-trailblazer", 13900),
    ("carroscom", "https://carros.com/car/b81740f31aee4629b3c8d1f7302a804f-p86776/", 9500),
    ("motorasv", "https://motorasv.com/cars/5122d37b-997d-478c-9b16-863b40dca5e4", 7200),
    ("disaz", "https://www.disazautos.com/product-page/kia-seltos-2023", 18900),
    ("autospublicidad", "https://www.autospublicidad.com/sv/detalles?auto=toyota-tacoma&id=73", 23500),
]
OUT = Path("/tmp/carly-multisite-browser")


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"staging": BASE, "cases": [], "passed": 0, "total": len(CASES)}
    async with async_playwright() as browser_tool:
        browser = await browser_tool.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1280, "height": 960})
        await page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        for slug, url, expected in CASES:
            result = {"source": slug, "url": url, "checks": {}, "error": None}
            try:
                await page.locator("#url").fill(url)
                await page.locator("#send").click()
                await page.locator("#card").wait_for(state="visible", timeout=32000)
                price = await page.locator("#price").inner_text()
                result["checks"]["price"] = "$" + format(expected, ",") in price
                result["title"] = await page.locator("#title").inner_text()
                result["checks"]["title"] = bool(result["title"])
                result["checks"]["year_visible"] = "Año · " in (await page.locator("#year").inner_text())
                result["checks"]["km_visible"] = "km" in (await page.locator("#km").inner_text()) and "no disponible" not in (await page.locator("#km").inner_text()).lower()
                try:
                    await page.wait_for_function(
                        "document.getElementById('photo').naturalWidth > 0", timeout=11000
                    )
                    result["checks"]["image_loaded"] = True
                except Exception:
                    result["checks"]["image_loaded"] = False
                    result["image_status"] = await page.locator("#photo-status").inner_text()
                await page.screenshot(path=str(OUT / (slug + ".png")), full_page=True)
            except Exception as exc:
                result["error"] = type(exc).__name__ + ": " + str(exc)[:180]
                await page.screenshot(path=str(OUT / (slug + "-error.png")), full_page=True)
            result["passed"] = bool(result["checks"]) and all(result["checks"].values()) and result["error"] is None
            report["passed"] += int(result["passed"])
            report["cases"].append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        await browser.close()
    (OUT / "results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"passed":report["passed"],"total":report["total"]}))
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
