"""Live regression for changing buyer mission after an existing shortlist.

The old shortlist must stop being active evidence immediately after the buyer says
that they are changing what they want. Carly may reuse stable facts such as budget
when the buyer explicitly says so, but old cars/CTAs must not steer the new search.
"""
from __future__ import annotations

import json
import os
import urllib.request

BASE = os.environ.get("CARLY_BASE_URL", "https://cartrade-resolver.onrender.com").rstrip("/")


def post(messages, shown_cars=None):
    payload = json.dumps({
        "messages": messages,
        "country": "sv",
        "top_n": 6,
        "shown_cars": shown_cars,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/carly/chat",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "CarTrade-Carly-Reset-Eval/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=50) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    # A representative old city shortlist. It is intentionally echoed on every
    # request to reproduce a frontend that has not cleared its local state yet.
    old_cards = [
        {"make": "Kia", "model": "RIO", "year": 2021, "price_usd": 9400, "km": 32424, "body_type": "hatch"},
        {"make": "Mitsubishi", "model": "Mirage", "year": 2022, "price_usd": 9300, "km": 49000, "body_type": "hatch"},
    ]
    messages = [
        {"role": "assistant", "content": "Estoy optimizando para: ciudad, económico y fácil de estacionar."},
        {"role": "user", "content": "Busco un auto cómodo, seguro y eficiente para viajes largos"},
        {"role": "assistant", "content": "Ese es un perfil diferente. ¿Estás cambiando lo que buscas o pensando en un segundo carro?"},
        {"role": "user", "content": "Cambiando lo que busco"},
    ]

    result = post(messages, old_cards)
    if result.get("decision_state") != "rebuilding" or not result.get("clear_recommendations"):
        raise AssertionError(f"reset did not invalidate old shortlist: {result}")
    if result.get("favorite") is not None or result.get("recommendations"):
        raise AssertionError("old active recommendation state survived profile reset")

    reply = str(result.get("reply") or "")
    messages.append({"role": "assistant", "content": reply})
    messages.append({"role": "user", "content": "el mismo de antes"})
    result = post(messages, old_cards)
    if result.get("decision_state") != "rebuilding" or not result.get("clear_recommendations"):
        raise AssertionError("old cards became active again while new profile was still incomplete")

    print(json.dumps({"status": "PASS", "reset_state": "rebuilding", "old_cards_invalidated": True}, indent=2))


if __name__ == "__main__":
    main()
