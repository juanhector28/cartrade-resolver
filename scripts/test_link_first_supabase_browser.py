"""Exercise candidate single-file Netlify HTML using live Supabase synthetic backend.

Never changes the actual Netlify deployment. Chromium uses an intercepted
homepage response at the exact staging origin so that preflight / CORS behavior
matches an eventual deployment. Only fixed synthetic records are transmitted.
"""
from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "previews/link-first/staging-supabase.html").read_text(encoding="utf-8")
URL = "https://bright-dragon-cd29a3.netlify.app/"
BACKEND = "https://irnxvajksefkhllceazs.supabase.co/functions/v1/cartrade-link-first-staging-probe"


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        for label, viewport in (("desktop", {"width":1280, "height":900}), ("mobile", {"width":390, "height":844})):
            page = browser.new_page(viewport=viewport)
            page.route(URL, lambda route: route.fulfill(
                status=200, content_type="text/html", body=HTML
            ))
            payloads = []
            def inspect(req):
                if req.method == "POST":
                    assert req.url == BACKEND, f"Unexpected data submission to {req.url}"
                    payload = json.loads(req.post_data or "{}")
                    assert payload == {
                        "mode":"synthetic_demo",
                        "probe_id":"a4c3a9e4-2d7c-44ab-b53d-9b57409c2026",
                        "listing_url":"https://example.org/cartrade-demo-vehicle",
                        "consent_preview":True
                    }, "Never leak typed phone or user listing URL"
                    payloads.append(payload)
            page.on("request", inspect)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)[:180]))
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            assert page.locator("#ct-link-first-start").is_visible()
            page.locator("#heroInput").fill("https://www.facebook.com/marketplace/item/12345/")
            page.locator("#ct-link-first-start").click()
            assert page.locator("#ct-link-first-submit").is_disabled()
            page.locator("#ct-link-first-phone").fill("+503 7000 0000")
            page.locator("#ct-link-first-consent").check()
            page.locator("#ct-link-first-submit").click()
            page.get_by_text("Prueba técnica registrada").wait_for(timeout=20000)
            assert len(payloads) == 1, f"Expected 1 synthetic POST; actual {len(payloads)}"
            assert not errors, f"Unexpected browser errors {errors}"
            assert page.evaluate("window.CT_LINK_FIRST_RECEIPT == null"), "No real receipt ever produced"
            assert "NO se guardaron" in page.locator("#ct-link-first-dialog").inner_text()
            print("PASS: live Supabase simulated Netlify " + label + ", no buyer data sent")
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
