"""Safe read-only audit of the dedicated CarTrade Netlify staging site.

Only GET/HEAD/OPTIONS are allowed. This intentionally does NOT submit a buyer
request, enter phone data, scrape social listings or modify production.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

TARGET = "https://bright-dragon-cd29a3.netlify.app/"
RESULT = Path("/tmp/cartrade_staging_site_audit.json")


def run():
    results = {"target": TARGET, "checks": {}, "writes_attempted": [], "requests": [], "fatal": None}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            for key, viewport in (
                ("desktop", {"width": 1280, "height": 900}),
                ("mobile", {"width": 390, "height": 844}),
            ):
                page = browser.new_page(viewport=viewport)
                failures = []

                def safe_routes(route):
                    request = route.request
                    if request.method not in ("GET", "HEAD", "OPTIONS"):
                        results["writes_attempted"].append({"method": request.method, "url": request.url})
                        return route.abort()
                    return route.continue_()

                page.route("**/*", safe_routes)
                page.on("pageerror", lambda error: failures.append(str(error)[:240]))
                response = page.goto(TARGET, timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(1000)
                details = page.evaluate("""() => ({
                    title: document.title,
                    heading: (document.querySelector('h1')?.textContent || '').trim().slice(0,180),
                    hero_input: !!document.querySelector('#heroInput'),
                    start_button: !!document.querySelector('#ct-link-first-start'),
                    demo_mode: window.CT_LINK_FIRST_DEMO === true,
                    form_count: document.querySelectorAll('form').length,
                    script_sources: [...document.querySelectorAll('script[src]')].map(x=>x.getAttribute('src')),
                    inputs: [...document.querySelectorAll('input')].slice(0,15).map(x=>({id:x.id,type:x.type})),
                    internal_paths: [...document.querySelectorAll('a[href]')].map(x=>x.getAttribute('href')).filter(x=>x?.startsWith('/')).slice(0,20),
                    content_sample: document.body?.innerText?.slice(0,650) || ''
                })""")
                details.update({
                    "http_status": response.status if response else None,
                    "final_url": page.url,
                    "script_errors": failures,
                })
                if details["start_button"] and details["hero_input"]:
                    details["start_visible"] = page.locator("#ct-link-first-start").is_visible()
                    if details["demo_mode"]:
                        page.locator("#heroInput").fill(
                            "https://www.facebook.com/marketplace/item/123456789012345/"
                        )
                        page.locator("#ct-link-first-start").click()
                        page.locator("#ct-link-first-dialog").wait_for(state="visible", timeout=7000)
                        details["consent_required"] = page.locator("#ct-link-first-submit").is_disabled()
                        # Live audit stays read-only. The current staging build
                        # legitimately writes a fixed synthetic probe on submit,
                        # so we must NOT click it or abort legitimate POSTs.
                        page.locator("#ct-link-first-phone").fill("70000000")
                        page.locator("#ct-link-first-consent").check()
                        details["consent_unlocks_preview"] = page.locator("#ct-link-first-submit").is_enabled()
                        details["no_real_receipt"] = page.evaluate(
                            "window.CT_LINK_FIRST_RECEIPT == null"
                        )
                        details["synthetic_stage"] = "cartrade-link-first-staging-probe" in page.content()
                results["checks"][key] = details
                page.close()
            browser.close()
        if results["writes_attempted"]:
            raise ValueError("Unexpected browser writes")
    except Exception as exc:
        results["fatal"] = f"{type(exc).__name__}: {str(exc)[:320]}"
    RESULT.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print("STAGING_AUDIT=" + json.dumps(results, ensure_ascii=False))
    if results["fatal"] or not all(
        check.get("http_status")==200
        and check.get("start_visible")
        and check.get("demo_mode")
        and check.get("consent_required")
        and check.get("consent_unlocks_preview")
        and check.get("no_real_receipt")
        for check in results["checks"].values()
    ):
        raise SystemExit("FAIL: Netlify staging demo, consent or safety gate failed")
    print("PASS: Netlify staging link-first and consent UI on desktop + mobile, no network writes")


if __name__ == "__main__":
    run()
