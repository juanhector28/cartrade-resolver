"""Real inbox browser workflow, but with completely simulated Auth and data.

Exercises the shipped operator HTML in Chromium; never touches Supabase, Render,
production customers, OTP delivery, or the live buyer-intent write path.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from app.buyer_ops_page import PAGE

SITE = "https://buyerops.invalid"
EMAIL = "operator@cartrade.example"
ACCESS_TOKEN = "synthetic_otp_verified_jwt_for_browser_test_only"
REQUEST_ID = "c4b804cf-f580-4227-a598-bd4f02176ca2"


def main():
    events: list[tuple[str, str]] = []
    statuses: list[str] = []
    row = {
        "request_id": REQUEST_ID,
        "created_at": "2026-10-12T19:00:00Z",
        "buyer_contact": "70000000",
        "listing_url": "https://www.julajups.sv/anuncio/test-car",
        "car_name": "Toyota 4Runner 2019 · prueba",
        "price_usd": 27500,
        "status": "received",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1200, "height": 900})

        def route_request(route):
            req = route.request
            path = urlsplit(req.url).path
            events.append((req.method, path))
            data = json.loads(req.post_data or "{}") if req.method in ("POST", "PATCH") else {}
            status = 200
            payload: dict = {}
            if path == "/ops/solicitudes" and req.method == "GET":
                route.fulfill(status=200, content_type="text/html", body=PAGE)
                return
            if path == "/ops/auth/start" and req.method == "POST":
                assert data == {"email": EMAIL}
                status = 202
                payload = {"status": "if_authorized_code_sent"}
            elif path == "/ops/auth/verify" and req.method == "POST":
                assert data.get("email") == EMAIL
                if data.get("code") == "123456":
                    payload = {"access_token": ACCESS_TOKEN, "token_type": "bearer"}
                else:
                    status, payload = 401, {"detail": "Código inválido"}
            elif path == "/ops/api/solicitudes" and req.method == "GET":
                if req.headers.get("authorization") != "Bearer " + ACCESS_TOKEN:
                    status, payload = 401, {"detail": "Unauthorized"}
                else:
                    payload = {"items": [dict(row)], "offset": 0, "limit": 50}
            elif path == "/ops/api/solicitudes/" + REQUEST_ID and req.method == "PATCH":
                assert req.headers.get("authorization") == "Bearer " + ACCESS_TOKEN
                assert data.get("status") in {"received", "in_review", "contacted", "closed"}
                row["status"] = data["status"]
                statuses.append(row["status"])
                payload = {"request_id": REQUEST_ID, "status": row["status"]}
            else:
                raise AssertionError(f"Unexpected network request: {req.method} {path}")
            route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

        page.route("**/*", route_request)
        page.goto(SITE + "/ops/solicitudes", wait_until="domcontentloaded")
        assert page.locator("#login").is_visible()
        assert page.locator("#app").is_hidden()
        assert "70000000" not in page.locator("body").inner_text()
        assert not any(path == "/ops/api/solicitudes" for _, path in events)

        page.locator("#email").fill(EMAIL.upper())
        page.locator("#login-form button[type=submit]").click()
        page.locator("#verify-form").wait_for(state="visible")
        assert page.locator("#app").is_hidden()

        page.locator("#code").fill("000000")
        page.locator("#verify-form button[type=submit]").click()
        page.wait_for_function("document.getElementById('login-error').textContent.length > 0")
        assert page.locator("#app").is_hidden()
        assert not any(path == "/ops/api/solicitudes" for _, path in events)

        page.locator("#code").fill("123456")
        page.locator("#verify-form button[type=submit]").click()
        page.locator("#app").wait_for(state="visible")
        assert page.locator("#rows tr").count() == 1
        assert "70000000" in page.locator("#rows").inner_text()
        assert page.locator("#rows select").input_value() == "received"

        page.locator("#rows select").select_option("contacted")
        page.wait_for_function("document.querySelector('#rows select') && !document.querySelector('#rows select').disabled")
        assert statuses == ["contacted"]
        page.locator("#refresh").click()
        page.wait_for_function("document.querySelector('#rows select') && document.querySelector('#rows select').value === 'contacted'")

        assert page.evaluate("Object.keys(localStorage).length") == 0
        assert page.evaluate("Object.keys(sessionStorage).length") == 0
        assert not any(ACCESS_TOKEN in url for _, url in events)

        page.locator("#logout").click()
        assert page.locator("#app").is_hidden()
        assert page.locator("#login").is_visible()
        assert "70000000" not in page.locator("body").inner_text()
        browser.close()

    print("PASS: OTP error/success, no PII before auth, staff inbox, state update, logout, no browser token persistence")


if __name__ == "__main__":
    main()
