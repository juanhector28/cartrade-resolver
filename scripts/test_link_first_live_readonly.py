"""Public read-only smoke of CarTrade's live landing, never posts real leads.

The production link-first HTML is DEMO mode. Any POST/PUT/PATCH/DELETE request
is intercepted, aborted and treated as a test failure.
"""
from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://cartrade.live/"
LINK = "https://www.facebook.com/marketplace/item/123456789012345/"


def main():
    report = {"site": URL, "desktop": {}, "mobile": {}, "network_writes": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        for label, viewport in [
            ("desktop", {"width": 1280, "height": 900}),
            ("mobile", {"width": 375, "height": 812}),
        ]:
            page = browser.new_page(viewport=viewport, locale="es-SV")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)[:220]))

            def stop_write(route):
                req = route.request
                if req.method not in ("GET", "HEAD", "OPTIONS"):
                    report["network_writes"].append({"method": req.method, "url": req.url})
                    return route.abort()
                return route.continue_()

            page.route("**/*", stop_write)
            response = page.goto(URL + "?link_first_smoke=20261012", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)
            text = page.locator("body").inner_text(timeout=15000)
            report[label] = {
                "http_status": response.status if response else None,
                "title": page.title(),
                "has_link_first_hero": "Pega el enlace" in text,
                "has_demo_banner": "No se envían ni guardan solicitudes" in text,
                "has_cta": page.locator("#ct-link-first-start").count() > 0,
                "has_input": page.locator("#heroInput").count() > 0,
                "console_errors": errors,
            }
            if not report[label]["has_cta"] or not report[label]["has_input"]:
                report[label]["note"] = "The current live site is not the expected link-first preview."
                page.close()
                continue
            page.locator("#heroInput").fill(LINK)
            page.locator("#ct-link-first-start").click(timeout=5000)
            page.locator("#ct-link-first-dialog").wait_for(state="visible", timeout=5000)
            report[label]["has_consent"] = page.locator("#ct-link-first-consent").count() == 1
            report[label]["submit_initially_disabled"] = page.locator("#ct-link-first-submit").is_disabled()
            report[label]["dialog_visible"] = True
            # Do not input a real phone or perform production submissions.
            if report[label]["has_demo_banner"]:
                page.locator("#ct-link-first-phone").fill("70000000")
                page.locator("#ct-link-first-consent").check()
                page.locator("#ct-link-first-submit").click()
                report[label]["demo_finished"] = "Vista previa completada" in page.locator("#ct-link-first-dialog").inner_text()
            page.close()
        browser.close()
    Path("/tmp/link_first_live_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("LIVE_SMOKE_REPORT=" + json.dumps(report, ensure_ascii=False))
    ok = all(
        report[name].get("http_status") == 200 and
        report[name].get("has_link_first_hero") and
        report[name].get("has_cta") and
        report[name].get("has_demo_banner") and
        report[name].get("dialog_visible") and
        report[name].get("has_consent") and
        report[name].get("submit_initially_disabled") and
        report[name].get("demo_finished")
        for name in ("desktop", "mobile")
    )
    assert not report["network_writes"], "Attempted network write during demo"
    if not ok:
        raise SystemExit("FAIL: live site does not yet match demo HTML or a stage check failed")
    print("PASS: live desktop + mobile link-first DEMO, consent, zero network writes")


if __name__ == "__main__":
    main()
