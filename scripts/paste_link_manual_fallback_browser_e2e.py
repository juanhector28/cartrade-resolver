"""Offline Chromium E2E: unsupported link -> manual vehicle card, no writes.

Uses the actual committed staging page template but intercepts every network
request. Never fetches sites, real leads, live resolver or Supabase.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.paste_link_manual_fallback import attach_manual_fallback

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app" / "paste_link_staging.py"
ORIGIN = "https://carly-manual-fallback.invalid"
UNKNOWN = "https://not-listed.example/anuncio/toyota-corolla-2019"
SUPPORTED = "https://www.carroselsalvador.com/anuncios/kia-sportage-2006/"


def staging_html() -> str:
    """Extract HTML static constant without importing live backend dependencies."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    matches = [
        n.value for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "STAGING_PAGE" for t in n.targets)
        and isinstance(n.value, ast.Constant)
    ]
    if len(matches) != 1:
        raise ValueError("Expected single literal staging HTML constant")
    return attach_manual_fallback(ast.literal_eval(matches[0]))


def main() -> None:
    html = staging_html()
    requests = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1180, "height": 880})
        page.on("dialog", lambda d: d.dismiss())

        def intercept(route):
            request = route.request
            path = request.url.split(ORIGIN, 1)[-1]
            requests.append({"method": request.method, "path": path})
            if request.method == "GET" and path == "/":
                route.fulfill(status=200, body=html, content_type="text/html")
            elif request.method == "GET" and path == "/api/coverage":
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "pilot_candidates": 3, "core_field_samples_verified": 9
                }))
            elif request.method == "GET" and path == "/api/sources":
                route.fulfill(status=200, content_type="application/json", body='{"sources":[]}')
            elif request.method == "POST" and path == "/api/resolve":
                payload = json.loads(request.post_data or "{}")
                if payload.get("url") == UNKNOWN:
                    route.fulfill(status=400, content_type="application/json", body=json.dumps({
                        "detail": "Enlace no habilitado para extracción automática."
                    }))
                elif payload.get("url") == SUPPORTED:
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({
                        "title": "Kia Sportage 2006", "price_usd": 4900, "year": 2006,
                        "km": None, "source_url": SUPPORTED, "photos": [],
                    }))
                else:
                    raise AssertionError("Unexpected resolver URL: " + repr(payload))
            else:
                raise AssertionError("Unexpected network request: " + request.method + " " + request.url)

        page.route("**/*", intercept)
        page.goto(ORIGIN + "/", wait_until="domcontentloaded")
        page.locator("#url").fill(UNKNOWN)
        page.locator("#send").click()
        page.locator("#manual-helper").wait_for(state="visible", timeout=15000)
        assert "Enlace no habilitado" in page.locator("#status").inner_text()
        assert page.locator("#card").is_hidden()
        assert sum(r["method"] == "POST" for r in requests) == 1

        # Manual values must be explicitly provided by the buyer.
        page.locator("#manual-title").fill("<img src=x onerror=alert(1)> Toyota Corolla")
        page.locator("#manual-price").fill("12600")
        page.locator("#manual-year").fill("2019")
        page.locator("#manual-form button[type=submit]").click()
        assert page.locator("#card").is_visible()
        assert page.locator("#manual-helper").is_hidden()
        assert "No verificados" in page.locator("#card .meta").text_content()
        assert "<img src=x" in page.locator("#title").inner_text()
        assert page.locator("#card img").count() == 1  # existing image placeholder only
        assert page.locator("#photo").is_hidden()
        assert page.locator("#source").get_attribute("href") == UNKNOWN
        assert "$12,600" in page.locator("#price").inner_text()
        assert "2019" in page.locator("#year").inner_text()
        assert "no recuperó ni verificó" in page.locator("#photo-status").inner_text()
        assert sum(r["method"] == "POST" for r in requests) == 1

        # A successful automated extraction always clears the manual badge.
        page.locator("#url").fill(SUPPORTED)
        page.locator("#send").click()
        page.wait_for_function("document.getElementById('title').textContent === 'Kia Sportage 2006'", timeout=15000)
        assert page.locator("#manual-helper").is_hidden()
        assert page.locator("#card .meta").text_content().strip() == "Ficha recuperada de la fuente"
        assert "$4,900" in page.locator("#price").inner_text()
        assert page.locator("#source").get_attribute("href") == SUPPORTED

        assert len([r for r in requests if r["method"] == "POST"]) == 2
        assert all(r["path"] == "/api/resolve" for r in requests if r["method"] == "POST")
        browser.close()
    print("PASS: unsupported link -> manual nonverified card -> verified extraction; no writes, no leads, no XSS")


if __name__ == "__main__":
    main()
