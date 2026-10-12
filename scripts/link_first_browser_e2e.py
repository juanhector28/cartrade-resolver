"""Offline browser E2E for link-first buyer request, with mocked API only.

Neither the test nor its frontend calls real Supabase, lenders or sellers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "assets" / "cartrade_link_first_request.js"
URL = "https://www.facebook.com/marketplace/item/123456789/?ref=share"
FIXTURE = """<!doctype html><html><head></head><body>
<div id="lp9">
  <div class="search-shell">
    <button class="search-tab" data-mode="describe">Describe</button>
    <button class="search-tab active" data-mode="link">Pega el enlace</button>
    <input id="heroInput" type="text"/>
  </div>
</div>
</body></html>"""


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        seen = []
        state = {"success": True}

        def route_request(route):
            req = route.request
            if req.url == "https://cartrade-link-first.invalid/" and req.method == "GET":
                route.fulfill(status=200, content_type="text/html", body=FIXTURE)
            elif req.url.endswith("/buyer-intents") and req.method == "POST":
                data = json.loads(req.post_data or "{}")
                seen.append(data)
                if state["success"]:
                    route.fulfill(status=201, content_type="application/json", body=json.dumps({
                        "status": "received", "request_id": data["request_id"],
                    }))
                else:
                    route.fulfill(status=503, content_type="application/json",
                                  body='{"detail":"service unavailable"}')
            else:
                raise AssertionError("Unexpected remote request: " + req.method + " " + req.url)

        page.route("**/*", route_request)
        page.goto("https://cartrade-link-first.invalid/", wait_until="domcontentloaded")
        page.evaluate("window.CARTRADE_API={base:'https://api.cartrade.invalid'}")
        page.add_script_tag(path=str(JS))
        assert page.locator("#ct-link-first-start").is_visible()
        page.locator("#heroInput").fill(URL)
        page.locator("#ct-link-first-start").click()
        page.locator("#ct-link-first-dialog").wait_for(state="visible")
        assert page.locator("#ct-link-first-submit").is_disabled()
        assert len(seen) == 0

        page.locator("#ct-link-first-consent").check()
        page.locator("#ct-link-first-phone").fill("123")
        page.locator("#ct-link-first-submit").click()
        assert "WhatsApp válido" in page.locator("#ct-link-first-errors").inner_text()
        assert len(seen) == 0
        page.locator("#ct-link-first-phone").fill("+503 7000 0000")
        page.locator("#ct-link-first-submit").click()
        page.wait_for_function("window.CT_LINK_FIRST_RECEIPT && window.CT_LINK_FIRST_RECEIPT.status === 'received'")
        assert len(seen) == 1
        assert seen[0]["listing_url"] == URL
        assert seen[0]["buyer_contact"] == "50370000000"
        assert seen[0]["consent_to_contact"] is True
        assert "car_name" not in seen[0] and "price_usd" not in seen[0]
        assert "Solicitud registrada" in page.locator("#ct-link-first-dialog").inner_text()
        page.locator("#ct-link-first-dialog button").click()
        assert page.locator("#ct-link-first-dialog").count() == 0

        # A failed backend must not falsely confirm receipt.
        state["success"] = False
        page.evaluate("delete window.CT_LINK_FIRST_RECEIPT")
        page.locator("#ct-link-first-start").click()
        page.locator("#ct-link-first-consent").check()
        page.locator("#ct-link-first-phone").fill("70000000")
        page.locator("#ct-link-first-submit").click()
        page.wait_for_function("document.getElementById('ct-link-first-errors')?.textContent.includes('No se pudo registrar')")
        assert page.locator("#ct-link-first-dialog").is_visible()
        assert page.evaluate("window.CT_LINK_FIRST_RECEIPT") is None
        assert len(seen) == 2
        page.locator("#ct-link-first-cancel").click()

        # Mode-specific CTA disappears outside link mode.
        page.locator(".search-tab[data-mode=link]").evaluate("(e)=>e.classList.remove('active')")
        page.locator(".search-tab[data-mode=describe]").evaluate("(e)=>e.classList.add('active')")
        page.locator(".search-tab[data-mode=describe]").click()
        assert page.locator("#ct-link-first-entry").is_hidden()
        browser.close()

    print("PASS: link-only buyer request, explicit WhatsApp consent, verified receipt, failure fallback, no extractor calls")


if __name__ == "__main__":
    run()
