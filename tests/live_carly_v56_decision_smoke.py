"""Live smoke for Carly's v55/v56 follow-up routing.

Manual-only production smoke. This reproduces the UI context contamination that
previously pushed model questions back into the unit checklist, then verifies that
an explicit purchase-decision follow-up reaches the decisive unit path.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

BASE = os.environ.get("CARLY_BASE_URL", "https://cartrade-resolver.onrender.com").rstrip("/")


def post_chat(messages, shown_cars):
    payload = json.dumps({
        "messages": messages,
        "country": "gt",
        "top_n": 6,
        "shown_cars": shown_cars,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/carly/chat",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Carly-v56-Live-Smoke/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=55) as response:
        return json.loads(response.read().decode("utf-8"))


def norm(text):
    s = str(text or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def main():
    hrv = {
        "id": "live-smoke-hrv-2023",
        "url": "https://example.com/hrv-2023",
        "make": "Honda",
        "model": "HR-V",
        "year": 2023,
        "km": 19,
        "price_usd": 19000,
        "monthly_est": 402,
        "body_type": "SUV",
        "value_delta_pct": 2,
    }
    cx5 = {
        "id": "live-smoke-cx5-2024",
        "url": "https://example.com/cx5-2024",
        "make": "Mazda",
        "model": "CX-5",
        "year": 2024,
        "km": 18000,
        "price_usd": 26000,
        "monthly_est": 573,
        "body_type": "SUV",
        "value_delta_pct": 1,
    }
    shown = [hrv, cx5]

    messages = [
        {"role": "user", "content": "Busco un SUV familiar para llevar a mis hijos al colegio."},
        {"role": "assistant", "content": "Entre tus finalistas están el Honda HR-V 2023 y el Mazda CX-5 2024."},
        {
            "role": "user",
            "content": (
                "¿Cuáles son los pros y cons de este modelo?\n\n"
                "[CONTEXTO ACTIVO DE CARTRADE: Honda HR-V 2023; precio USD 19,000; "
                "19 km; cuota ~USD 402/mes; VIN pendiente; ver más opciones disponible]"
            ),
        },
    ]
    model = post_chat(messages, shown)
    model_reply = str(model.get("reply") or "").strip()
    if model.get("route_precedence") != "model_intelligence_v55" or model.get("model_scope") is not True:
        raise AssertionError(f"pros/cons missed model-intelligence route: {model}")
    model_norm = norm(model_reply)
    forbidden = ("antes de comprar", "vin/chasis", "deja ~", "margen frente a tu techo")
    if any(norm(x) in model_norm for x in forbidden):
        raise AssertionError(f"model answer leaked unit-checklist language: {model_reply}")

    messages.append({"role": "assistant", "content": model_reply})
    messages.append({"role": "user", "content": "¿Y es buena compra esta unidad del Honda HR-V 2023?"})
    buy = post_chat(messages, shown)
    buy_reply = str(buy.get("reply") or "").strip()
    if buy.get("route_precedence") != "buy_decision_v56" or buy.get("buyer_decision") is not True:
        raise AssertionError(f"good-buy question missed v56 route: {buy}")
    if "VEREDICTO" not in buy_reply.upper():
        raise AssertionError(f"good-buy reply lacked decisive verdict structure: {buy_reply}")
    if "19" in buy_reply and not any(x in norm(buy_reply) for x in ("inusualmente bajos", "confirmar", "confirmado")):
        raise AssertionError(f"implausible mileage was rewarded without caution: {buy_reply}")

    messages.append({"role": "assistant", "content": buy_reply})
    messages.append({"role": "user", "content": "¿Cuál escogerías entre este Honda y el Mazda CX-5 2024?"})
    choice = post_chat(messages, shown)
    choice_reply = str(choice.get("reply") or "").strip()
    if not choice_reply:
        raise AssertionError("choice follow-up returned an empty reply")
    if not any(model_name in norm(choice_reply) for model_name in ("hr-v", "cx-5")):
        raise AssertionError(f"choice follow-up lost the shortlist: {choice_reply}")

    print(json.dumps({
        "status": "PASS",
        "model_route": model.get("route_precedence"),
        "buy_route": buy.get("route_precedence"),
        "choice_reply": choice_reply,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
