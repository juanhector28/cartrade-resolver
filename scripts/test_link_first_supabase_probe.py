"""Exercise real Supabase STAGING synthetic-only endpoint without storing buyer data.

Uses only PUBLIC anon JWT embedded in the single-file preview. This key is
intended to be public; no service role or personal information is used.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "previews" / "link-first" / "staging-supabase.html"
FUNCTION = "https://irnxvajksefkhllceazs.supabase.co/functions/v1/cartrade-link-first-staging-probe"
ORIGIN = "https://bright-dragon-cd29a3.netlify.app"
PROBE = {
    "mode": "synthetic_demo",
    "probe_id": "a4c3a9e4-2d7c-44ab-b53d-9b57409c2026",
    "listing_url": "https://example.org/cartrade-demo-vehicle",
    "consent_preview": True,
}


def call(method, key, data=None, origin=ORIGIN):
    headers = {
        "origin": origin,
        "apikey": key,
        "authorization": "Bearer " + key,
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(
        FUNCTION, method=method, headers=headers,
        data=json.dumps(data).encode("utf-8") if data is not None else None
    )
    try:
        with urlopen(req, timeout=30) as res:
            return res.status, res.headers, json.loads(res.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, exc.headers, json.loads(exc.read().decode("utf-8"))


def main():
    text = HTML.read_text(encoding="utf-8")
    keys = re.findall(r'const anon = "(eyJ[A-Za-z0-9_.-]{50,})";', text)
    assert len(keys) == 1, "Expected exactly one public JWT in staging HTML"
    anon = keys[0]
    assert "CT_LINK_FIRST_DEMO = true" in text
    assert "SUPABASE_SERVICE_ROLE_KEY" not in text
    assert "buyer_contact:" not in text.split("if (window.CT_LINK_FIRST_DEMO === true)")[1].split("if (!api)")[0]

    status, headers, health = call("GET", anon)
    assert status == 200, f"Health expected 200; got {status}: {health}"
    assert health.get("synthetic_only") is True and health.get("intake_enabled") is False

    status, headers, receipt = call("POST", anon, PROBE)
    assert status == 200, f"Synthetic POST failed: {status}: {receipt}"
    assert receipt.get("status") == "synthetic_probe_recorded"
    assert receipt.get("buyer_data_recorded") is False
    assert receipt.get("real_intake_enabled") is False
    assert receipt.get("probe_id") == PROBE["probe_id"]

    bad = dict(PROBE, buyer_contact="70000000")
    status, _, data = call("POST", anon, bad)
    assert status == 422, f"Contact storage must be rejected: {status} {data}"
    status, _, data = call("POST", anon, PROBE, origin="https://not-cartrade.invalid")
    assert status == 403, f"External site blocked expected 403: {status} {data}"
    print("PASS: Supabase staging JWT, synthetic receipt, no buyer data, invalid payload and origin rejected")


if __name__ == "__main__":
    main()
