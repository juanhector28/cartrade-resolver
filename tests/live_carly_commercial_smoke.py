"""Live production smoke for Carly's commercial-advisory layer."""
from __future__ import annotations

import json
import os
import urllib.request

BASE = os.environ.get("CARLY_BASE_URL", "https://cartrade-resolver.onrender.com").rstrip("/")


def post(payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + "/carly/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    first_user = "Necesito un auto compacto para ciudad, económico y fácil de estacionar."
    r1 = post({"messages": [{"role": "user", "content": first_user}], "country": "sv", "top_n": 6, "shown_cars": []})
    reply1 = str(r1.get("reply") or "")
    if r1.get("phase") == "conversation":
        expected = "¿Prefieres pensar en precio total o en una cuota mensual cómoda?"
        if expected not in reply1:
            raise SystemExit(f"FAIL: affordability question is not financing-friendly: {reply1}")
        messages = [
            {"role": "user", "content": first_user},
            {"role": "assistant", "content": reply1},
            {"role": "user", "content": "Una cuota cómoda sería hasta $350 al mes."},
        ]
        r2 = post({"messages": messages, "country": "sv", "top_n": 6, "shown_cars": []})
    else:
        r2 = r1

    if r2.get("phase") != "recommendation":
        raise SystemExit(f"FAIL: expected recommendation, got {r2.get('phase')}: {r2.get('reply')}")
    financing = r2.get("financing") or {}
    if financing.get("positioning") != "buying_power" or financing.get("optional") is not True:
        raise SystemExit(f"FAIL: financing contract missing/incorrect: {financing}")
    recs = r2.get("recommendations") or []
    if not recs:
        raise SystemExit("FAIL: no recommendations")
    financed = [c for c in recs if isinstance(c, dict) and isinstance(c.get("financing"), dict)]
    if not financed:
        raise SystemExit("FAIL: recommendation cards missing financing metadata")
    decision = r2.get("decision") or {}
    if (decision.get("financing") or {}).get("cta") != "Ver opciones de financiamiento":
        raise SystemExit(f"FAIL: Decision Room financing CTA missing: {decision.get('financing')}")

    low = str(r2.get("reply") or "").lower()
    for banned in ("qué debería preocuparte", "red flags", "banderas rojas"):
        if banned in low:
            raise SystemExit(f"FAIL: fear framing leaked into recommendation: {banned}: {low}")

    print(json.dumps({
        "status": "PASS",
        "phase": r2.get("phase"),
        "financing": financing,
        "first_car_financing": financed[0].get("financing"),
        "decision_id": decision.get("id"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
