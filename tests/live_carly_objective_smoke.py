"""Live product smoke for Carly's first-car objective.

This deliberately tests the deployed service, not internal functions. It fails
if Carly loses explicit buyer facts or recommends/exposes cars that violate the
buyer's hard limits.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("CARLY_BASE_URL", "https://cartrade-resolver.onrender.com").rstrip("/")


def post_chat(messages):
    payload = json.dumps({
        "messages": messages,
        "country": "sv",
        "top_n": 6,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/carly/chat",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "CarTrade-Carly-Smoke/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def assert_close(value, target, label, tolerance=0.01):
    if value is None or abs(float(value) - float(target)) > tolerance:
        raise AssertionError(f"{label}: expected {target}, got {value}")


def main():
    turns = [
        "Mi primer carro. Abajo de 65,000 kms de uso.",
        "Ir a la uni",
        "mmm unos 20km diarios. No tengo un budget",
        "12k",
    ]
    messages = []
    result = None

    for user_text in turns:
        messages.append({"role": "user", "content": user_text})
        result = post_chat(messages)
        reply = str(result.get("reply") or "").strip()
        if "[DIAG]" in reply:
            raise AssertionError(f"Carly returned diagnostic text: {reply}")
        if reply:
            messages.append({"role": "assistant", "content": reply})

    if not isinstance(result, dict):
        raise AssertionError("No final Carly response")
    if result.get("phase") != "recommendation":
        raise AssertionError(f"Expected recommendation after budget, got {result.get('phase')}: {result.get('reply')}")

    profile = result.get("profile") or {}
    assert_close(profile.get("daily_km"), 20, "daily_km")
    assert_close(profile.get("max_km"), 65000, "max_km")
    assert_close(profile.get("max_price"), 12000, "max_price")

    recs = result.get("recommendations") or []
    if not recs:
        raise AssertionError(f"No recommendations returned: {result.get('reply')}")

    exposed = recs + (result.get("explore") or [])
    violations = []
    for car in exposed:
        km = car.get("km")
        price = car.get("price_usd")
        name = " ".join(str(x) for x in (car.get("make"), car.get("model"), car.get("year")) if x)
        if km is not None and float(km) > 65000:
            violations.append(f"{name}: {km} km")
        if price is not None and float(price) > 12000:
            violations.append(f"{name}: ${price}")
    if violations:
        raise AssertionError("Hard-constraint violations exposed: " + "; ".join(violations[:10]))

    reply = str(result.get("reply") or "")
    if "100 km" in reply or "100km" in reply.replace(" ", "").lower():
        raise AssertionError("Search radius leaked into buyer usage context")

    print(json.dumps({
        "status": "PASS",
        "phase": result.get("phase"),
        "profile": {k: profile.get(k) for k in ("primary_job", "daily_km", "max_km", "max_price")},
        "recommendations": [
            {"car": " ".join(str(x) for x in (c.get("make"), c.get("model"), c.get("year")) if x),
             "km": c.get("km"), "price_usd": c.get("price_usd")}
            for c in recs
        ],
        "pool_size": result.get("pool_size"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
