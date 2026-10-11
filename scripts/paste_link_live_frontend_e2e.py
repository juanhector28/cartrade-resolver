"""Browser E2E for the public CarTrade link-to-request journey; resolver mocked.

Read-only: never posts to production resolver or financing providers.
"""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://www.julajups.sv/anuncio/toyota-4-runner-trd-2019-4x4-N3tSneYO52"
SITE = os.environ.get("CARTRADE_FRONTEND_URL", "https://cartrade.live")
OUT = Path(os.environ.get("E2E_ARTIFACTS", "/tmp/cartrade-ui-e2e"))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, calls, blocked_writes = {}, [], []
    report = {"scope": "Live frontend, mocked resolver; no banking or production writes", "site": SITE, "checks": checks}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        def route(request):
            u = request.request.url
            if "/resolve-link" in u and request.request.method == "POST":
                calls.append(json.loads(request.request.post_data or "{}"))
                request.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "platform": "unknown",
                    "title": {"value": "TOYOTA 4 RUNNER TRD 2019 4X4"},
                    "price_usd": {"value": 27500},
                    "year": {"value": 2019}, "km": None, "photos": [], "saved": False
                }))
            elif request.request.method.upper() not in ('GET', 'HEAD', 'OPTIONS'):
                blocked_writes.append({'method': request.request.method, 'url': u})
                request.abort()
            else:
                request.continue_()
        page.route("**/*", route)
        try:
            page.goto(SITE, wait_until="domcontentloaded", timeout=90000)
            page.add_script_tag(path="assets/cartrade_finance_handoff_preview.js")
            # Use the visible search UI, not the compatibility input hidden off-screen.
            page.locator("#lp9 .search-tab[data-mode=link]").click()
            page.locator("#heroInput").fill(URL)
            page.locator("#compareBtn").click()
            page.wait_for_function("document.body.innerText.includes('Pedir este auto')", timeout=45000)
            content = page.locator("body").inner_text()
            checks.update({
                "single_resolver_request": len(calls) == 1,
                "correct_url": len(calls) == 1 and calls[0].get("url") == URL,
                "original_link_preserved": page.evaluate("window.CT_LAST_URL") == URL,
                "correct_vehicle": "TOYOTA 4 RUNNER" in content.upper(),
                "correct_price": "$27,500" in content,
                "request_cta": "Pedir este auto" in content,
                "financing_message": "Comprarlo con financiamiento" in content,
                "whatsapp_step": "TU WHATSAPP" in content
            })
            # Request transition is local UI state; never submit real customer data.
            page.locator("#req-wa-input").fill("70000000")
            page.locator("#req-send").click()
            page.wait_for_function("document.body.innerText.includes('Pedido enviado.')", timeout=15000)
            after_request = page.locator("body").inner_text()
            checks["request_confirmation"] = "Pedido enviado." in after_request
            checks["vehicle_context_at_confirmation"] = "TOYOTA" in after_request.upper()
            checks["financing_is_conditional"] = "Si el vendedor se suma" in after_request
            checks["no_false_bank_preapproval"] = "Te pre-aprobamos financiamiento" in after_request and "Si el vendedor se suma" in after_request
            page.locator("#ct-finance-start").click()
            checks["finance_dialog_visible"] = page.locator("#ct-finance-overlay").is_visible()
            checks["consent_required"] = page.locator("#ct-finance-confirm").is_disabled()
            checks["finance_source_preserved"] = page.locator(".ct-finance-vehicle a").get_attribute("href") == URL
            page.locator("#ct-finance-consent").check()
            page.locator("#ct-finance-confirm").click()
            preview_context = page.evaluate("window.CT_FINANCE_CONTEXT")
            checks["financing_context"] = (
                preview_context is not None
                and preview_context.get("source_url") == URL
                and preview_context.get("price_usd") == 27500
                and preview_context.get("year") == 2019
                and preview_context.get("financing_status") == "not_started"
            )
            checks["no_false_bank_submission"] = "Ninguna solicitud bancaria ha sido enviada" in page.locator("#ct-finance-overlay").inner_text()
            page.screenshot(path=str(OUT / "cartrade-finance-handoff.png"), full_page=False)
            page.screenshot(path=str(OUT / "cartrade-ui-request.png"), full_page=False)
            page.screenshot(path=str(OUT / "cartrade-ui.png"), full_page=False)
        except Exception as exc:
            report["error"] = str(exc)[:600]
        finally:
            browser.close()
    report["requests"] = calls
    report["blocked_non_resolver_writes"] = blocked_writes
    report["success"] = bool(checks) and all(checks.values()) and "error" not in report
    (OUT / "result.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, ensure_ascii=False))
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
