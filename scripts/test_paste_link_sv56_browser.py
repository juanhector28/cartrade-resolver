"""Headless browser proof of source-recognition fallback, zero third-party fetches."""
from __future__ import annotations

import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8788"


def wait_for_local_server():
    for _ in range(100):
        try:
            with urlopen(BASE + "/health", timeout=1) as res:
                if res.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise AssertionError("Staging server failed to start")


def main():
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.paste_link_staging:app",
         "--host", "127.0.0.1", "--port", "8788"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        wait_for_local_server()
        with sync_playwright() as engine:
            browser = engine.chromium.launch(headless=True, args=["--no-sandbox"])
            for label, viewport in (
                ("desktop", {"width": 1280, "height": 800}),
                ("mobile", {"width": 390, "height": 844}),
            ):
                context = browser.new_context(viewport=viewport)
                page = context.new_page()
                offsite = []
                errors = []

                def only_local(route):
                    req = route.request
                    if not req.url.startswith(BASE + "/"):
                        offsite.append(req.url)
                        return route.abort()
                    return route.continue_()

                page.route("**/*", only_local)
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.goto(BASE, wait_until="domcontentloaded")
                assert page.locator("#url").is_visible()
                for link, name in (
                    ("https://www.toyota.com.sv/vehiculos/corolla", "Toyota"),
                    ("https://www.encuentra24.com/el-salvador-es/autos-usados/prueba/12345678", "Encuentra24"),
                    ("https://www.baccredomatic.com/es-sv/personas/catalogo-de-vehiculos#vehicle-95036", "BAC"),
                ):
                    page.locator("#url").fill(link)
                    page.locator("#send").click()
                    page.get_by_text("Fuente identificada: " + name, exact=False).wait_for(timeout=12000)
                    assert page.locator("#manual-helper").is_visible()
                    assert "no se guardó" in page.locator("#status").inner_text()
                    assert page.locator("#card").is_hidden()
                assert not offsite, "Recognition attempted a third-party GET: " + repr(offsite)
                assert not errors, "Unexpected JS exception: " + repr(errors)
                print("PASS " + label + ": 3 different SV references, no scraping or writes")
                context.close()
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


if __name__ == "__main__":
    main()
