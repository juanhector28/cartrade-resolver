"""Live regression for Carly UI-state + expanded-card context.

Simulates the frontend revealing explore cards but accidentally echoing only the
original curated recommendations back to Carly. The backend must recover a named
real explore car instead of denying it, and market-comparison animation may only
be requested on a turn that actually produced a shortlist.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

BASE = os.environ.get("CARLY_BASE_URL", "https://cartrade-resolver.onrender.com").rstrip("/")


def post_chat(messages, shown_cars=None):
    payload = json.dumps({
        "messages": messages,
        "country": "sv",
        "top_n": 6,
        "shown_cars": shown_cars or None,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/carly/chat",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Carly-UI-Context-Smoke/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=55) as response:
        return json.loads(response.read().decode("utf-8"))


def car_name(car):
    return " ".join(str(x) for x in (car.get("make"), car.get("model"), car.get("year")) if x)


def norm(text):
    s = str(text or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def main():
    turns = [
        "Mi primer carro. Abajo de 65,000 kms de uso.",
        "Ir a la uni",
        "mmm unos 20km diarios. No tengo un budget",
        "12k",
    ]
    messages = []
    result = None
    for text in turns:
        messages.append({"role": "user", "content": text})
        result = post_chat(messages)
        reply = str(result.get("reply") or "").strip()
        if not reply:
            raise AssertionError("empty Carly reply")
        if result.get("phase") == "conversation" and result.get("show_market_animation") is True:
            raise AssertionError("market animation requested during ordinary conversation")
        messages.append({"role": "assistant", "content": reply})

    if result.get("phase") != "recommendation":
        raise AssertionError("initial journey did not reach recommendation")
    if result.get("show_market_animation") is not True:
        raise AssertionError("new shortlist did not request market animation")

    recs = result.get("recommendations") or []
    explore = result.get("explore") or []
    rec_keys = {(c.get("make"), c.get("model"), c.get("year")) for c in recs}
    target = next(
        (
            c for c in explore
            if c.get("make") and c.get("model") and c.get("year")
            and (c.get("make"), c.get("model"), c.get("year")) not in rec_keys
        ),
        None,
    )
    if not target:
        raise AssertionError("no distinct explore card available for regression")

    name = car_name(target)
    question = f"Cuéntame más del {name}: ¿por qué podría servirme y qué debería preocuparme?"
    messages.append({"role": "user", "content": question})

    # Deliberately send only original recommendations, reproducing the current UI bug.
    follow = post_chat(messages, shown_cars=recs)
    reply = str(follow.get("reply") or "").strip()
    n = norm(reply)

    if follow.get("phase") != "conversation":
        raise AssertionError(f"explore follow-up restarted search: {follow.get('phase')}")
    if follow.get("show_market_animation") is True:
        raise AssertionError("market animation requested for explore-card follow-up")
    if norm(target.get("model")) not in n or str(target.get("year")) not in reply:
        raise AssertionError(f"Carly did not stay on requested explore car: {reply}")

    denial_markers = (
        "no esta entre las unidades que te mostre",
        "no está entre las unidades que te mostré",
        "no tengo datos de precio",
        "no tengo datos de esa unidad",
        "no puedo recomendartelo ni analizarlo",
        "no puedo recomendártelo ni analizarlo",
    )
    if any(norm(x) in n for x in denial_markers):
        raise AssertionError(f"Carly falsely denied real explore car: {reply}")

    print(json.dumps({
        "status": "PASS",
        "explore_car": name,
        "show_market_animation_initial": result.get("show_market_animation"),
        "show_market_animation_followup": follow.get("show_market_animation"),
        "reply": reply,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
