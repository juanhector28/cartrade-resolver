"""End-to-end Chromium checks for the EXACT Netlify preview build.

All requests are local or mocked; no real buyer is contacted or saved.
"""
from __future__ import annotations

import json
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

from scripts.build_link_first_netlify import build

SAMPLE = "https://www.facebook.com/marketplace/item/789123456/?ref=share"


def main():
    with tempfile.TemporaryDirectory(prefix="cartrade-link-first-") as root:
        output = Path(root) / "netlify"
        build(output)

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(output), **kwargs)
            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        runner = threading.Thread(target=server.serve_forever, daemon=True)
        runner.start()
        url = f"http://127.0.0.1:{server.server_port}/"

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                page = browser.new_page(viewport={"width": 1280, "height": 850})
                writes = []
                page.on("request", lambda req: writes.append(req.url) if req.method != "GET" else None)
                page.goto(url, wait_until="load", timeout=30000)
                assert page.title() == "CarTrade | Pega el enlace"
                assert page.locator("#ct-link-first-start").is_visible()
                assert "No se envían ni guardan solicitudes" in page.locator("body").inner_text()
                page.locator("#heroInput").fill(SAMPLE)
                page.locator("#ct-link-first-start").click()
                page.locator("#ct-link-first-dialog").wait_for(state="visible")
                assert page.locator("#ct-link-first-submit").is_disabled()
                page.locator("#ct-link-first-phone").fill("+503 7000-0000")
                page.locator("#ct-link-first-consent").check()
                page.locator("#ct-link-first-submit").click()
                assert "Vista previa completada" in page.locator("#ct-link-first-dialog").inner_text()
                assert "No enviamos ni guardamos" in page.locator("#ct-link-first-dialog").inner_text()
                assert writes == [], f"Preview made non-GET requests: {writes}"
                assert page.evaluate("window.CT_LINK_FIRST_RECEIPT || null") is None

                # Same frontend module, but with all outbound calls mocked.
                received = []
                def backend(route):
                    req = route.request
                    body = json.loads(req.post_data or "{}")
                    received.append(body)
                    route.fulfill(status=201, content_type="application/json", body=json.dumps({
                        "status": "received", "request_id": body["request_id"]
                    }))
                page.route("https://mock-api.invalid/buyer-intents", backend)
                page.locator("#ct-link-first-dialog button").click()
                page.evaluate("window.CT_LINK_FIRST_DEMO=false; window.CARTRADE_API.base='https://mock-api.invalid'")
                page.locator("#ct-link-first-start").click()
                page.locator("#ct-link-first-phone").fill("+503 7000-0000")
                page.locator("#ct-link-first-consent").check()
                page.locator("#ct-link-first-submit").click()
                page.wait_for_function("window.CT_LINK_FIRST_RECEIPT?.status === 'received'")
                assert received and received[0]["listing_url"] == SAMPLE
                assert received[0]["buyer_contact"] == "50370000000"
                assert received[0]["consent_to_contact"] is True
                assert "car_name" not in received[0] and "price_usd" not in received[0]
                assert "Solicitud registrada" in page.locator("#ct-link-first-dialog").inner_text()

                mobile = browser.new_page(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
                mobile.goto(url, wait_until="load")
                assert mobile.locator("#ct-link-first-start").is_visible()
                assert mobile.locator("#heroInput").is_visible()
                browser.close()
        finally:
            server.shutdown()
            runner.join(timeout=5)
    print("PASS: full Netlify demo, no writes, consent, mock receipt, mobile preview")


if __name__ == "__main__":
    main()
