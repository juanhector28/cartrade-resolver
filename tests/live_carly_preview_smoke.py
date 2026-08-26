"""Live regression for Carly's preview-first intake.

Reproduces the product feedback: a buyer names a Prado and down payment, answers
one affordability question, and must see market instead of entering a long form.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("CARLY_BASE_URL", "https://cartrade-resolver.onrender.com").rstrip("/")


def post_chat(messages):
    req = urllib.request.Request(
        BASE + "/carly/chat",
        data=json.dumps({"messages": messages, "country": "sv", "top_n": 6}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "CarTrade-Preview-Smoke/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    messages = [{
        "role": "user",
        "content": "Quiero un Prado, tengo aproximadamente $3,000 de prima.",
    }]
    first = post_chat(messages)

    if first.get("phase") == "recommendation":
        result = first
        asked = 0
    else:
        reply = str(first.get("reply") or "").strip()
        if not reply:
            raise AssertionError("Carly returned an empty first response")
        if "?" not in reply and "¿" not in reply:
            raise AssertionError(f"Expected a useful first question or preview, got: {reply}")
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": "$1,200 al mes máximo."})
        result = post_chat(messages)
        asked = 1

    if result.get("phase") != "recommendation":
        raise AssertionError(
            "Carly kept interrogating after enough information for a preview: "
            + str(result.get("reply") or result)
        )
    if not result.get("recommendations"):
        raise AssertionError("Preview-first returned no market cards")
    if result.get("preview") is not True:
        raise AssertionError(f"First shortlist is not marked as preview: {result.get('preview')}")
    qcount = result.get("preview_question_count")
    if isinstance(qcount, int) and qcount > 2:
        raise AssertionError(f"Preview took too many questions: {qcount}")
    if not result.get("decision_room") or not isinstance(result.get("decision"), dict):
        raise AssertionError("Preview did not enter the Decision Room")

    print(json.dumps({
        "status": "PASS",
        "questions_before_preview": qcount if qcount is not None else asked,
        "recommendations": [
            " ".join(str(c.get(k)) for k in ("make", "model", "year") if c.get(k))
            for c in (result.get("recommendations") or [])[:3]
        ],
        "preview_reason": result.get("preview_reason"),
        "decision_id": (result.get("decision") or {}).get("id"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
