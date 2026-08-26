"""Live product-quality smoke for Carly after the shortlist.

Tests the deployed service as a buyer would use it: pros/cons on every curated
recommendation, comparisons, uncertainty about unknown facts, CarTrade next-step
advice, and buyer corrections. The goal is mission quality, not endpoint health.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("CARLY_BASE_URL", "https://cartrade-resolver.onrender.com").rstrip("/")
COUNTRY = "sv"


def post_chat(messages, shown_cars=None, top_n=6):
    payload = json.dumps({
        "messages": messages,
        "country": COUNTRY,
        "top_n": top_n,
        "shown_cars": shown_cars or None,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/carly/chat",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "CarTrade-Carly-Followup-Smoke/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def norm(text):
    s = str(text or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def car_name(car):
    return " ".join(str(x) for x in (car.get("make"), car.get("model"), car.get("year")) if x)


def ensure_clean_reply(result, label):
    if not isinstance(result, dict):
        raise AssertionError(f"{label}: non-dict response")
    reply = str(result.get("reply") or "").strip()
    if not reply:
        raise AssertionError(f"{label}: empty reply")
    if "[DIAG]" in reply:
        raise AssertionError(f"{label}: diagnostic text leaked: {reply}")
    return reply


def initial_journey():
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
        reply = ensure_clean_reply(result, f"initial:{user_text}")
        messages.append({"role": "assistant", "content": reply})

    if result.get("phase") != "recommendation":
        raise AssertionError(f"initial: expected recommendation, got {result.get('phase')}: {result.get('reply')}")
    recs = result.get("recommendations") or []
    if len(recs) < 3:
        raise AssertionError(f"initial: expected >=3 recommendations, got {len(recs)}")
    return messages, result, recs


_ABSOLUTE_UNIT_CLAIMS = (
    "no te va a dar dolores de cabeza",
    "no te dara dolores de cabeza",
    "no te va a dar problemas",
    "no te dara problemas",
    "esta en buen estado",
    "esta limpia",
    "esta impecable",
    "sin problemas mecanicos",
    "sin problemas de documentos",
)
_UNSUPPORTED_EXACT_PATTERNS = (
    re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:km/l|km por litro|l/100\s*km)\b", re.I),
    re.compile(r"\b\d+(?:[.,]\d+)?\s*l(?:itros?)?\b", re.I),
    re.compile(r"\b\d+\s*(?:hp|caballos(?: de fuerza)?)\b", re.I),
    re.compile(r"\b\d+\s+airbags?\b", re.I),
)
_UNCERTAINTY_MARKERS = (
    "no tengo", "no aparece", "no esta en los datos", "no esta reportado",
    "no puedo confirmar", "no puedo verificar", "no esta confirmado",
    "hay que verificar", "requiere verificacion", "lo confirma la inspeccion",
    "la inspeccion", "verificarlo",
)


def assert_no_unverified_certainty(reply, label):
    n = norm(reply)
    for phrase in _ABSOLUTE_UNIT_CLAIMS:
        if norm(phrase) in n:
            raise AssertionError(f"{label}: unsupported certainty: {phrase!r}\n{reply}")


def assert_no_invented_exact_specs(reply, label):
    for pattern in _UNSUPPORTED_EXACT_PATTERNS:
        match = pattern.search(reply)
        if match:
            raise AssertionError(f"{label}: invented/unsupported exact spec {match.group(0)!r}\n{reply}")


def assert_market_pct_consistent(reply, car, label):
    percentages = [int(x) for x in re.findall(r"\b(\d{1,3})\s*%", reply)]
    if not percentages:
        return
    allowed = set()
    vd = car.get("value_delta_pct")
    if isinstance(vd, (int, float)):
        allowed.update({round(abs(vd)), int(abs(vd))})
    mp = car.get("match_pct")
    if isinstance(mp, (int, float)):
        allowed.update({round(abs(mp)), int(abs(mp))})
    # Ignore generic 100% phrases, but any market/match percentage must come from data.
    bad = [p for p in percentages if p != 100 and p not in allowed]
    if bad:
        raise AssertionError(f"{label}: percentage(s) not grounded in shown car data: {bad}; allowed={sorted(allowed)}\n{reply}")


def followup(base_messages, recs, text):
    messages = list(base_messages) + [{"role": "user", "content": text}]
    return post_chat(messages, shown_cars=recs)


def test_pros_cons(base_messages, recs, report):
    for car in recs:
        name = car_name(car)
        result = followup(
            base_messages, recs,
            f"Cuéntame más del {name}: ¿por qué me lo recomiendas y qué debería preocuparme?",
        )
        reply = ensure_clean_reply(result, f"pros-cons:{name}")
        n = norm(reply)
        model = norm(car.get("model"))
        year = str(car.get("year") or "")
        if model and model not in n:
            raise AssertionError(f"pros-cons:{name}: did not identify the requested model\n{reply}")
        if year and year not in reply:
            raise AssertionError(f"pros-cons:{name}: did not anchor the requested year\n{reply}")
        if "no te lo recomende" in n or "no lo recomende" in n:
            raise AssertionError(f"pros-cons:{name}: denied a car that is in Carly's curated recommendations\n{reply}")
        if not any(k in n for k in ("a favor", "pros", "ventaja", "gana", "punto fuerte", "te conviene", "cuadra")):
            raise AssertionError(f"pros-cons:{name}: no clear upside/reasoning\n{reply}")
        if not any(k in n for k in ("en contra", "contra", "preocupa", "trade-off", "tradeoff", "ojo", "verificar", "pero", "punto debil")):
            raise AssertionError(f"pros-cons:{name}: no honest downside/caveat\n{reply}")
        assert_no_unverified_certainty(reply, f"pros-cons:{name}")
        assert_no_invented_exact_specs(reply, f"pros-cons:{name}")
        assert_market_pct_consistent(reply, car, f"pros-cons:{name}")
        report.append({"test": "pros_cons", "car": name, "status": "PASS", "reply": reply})


def test_comparison(base_messages, recs, report):
    a, b = recs[0], recs[1]
    an, bn = car_name(a), car_name(b)
    result = followup(base_messages, recs, f"Entre el {an} y el {bn}, ¿cuál escogerías para mí y por qué?")
    reply = ensure_clean_reply(result, "comparison")
    n = norm(reply)
    for car in (a, b):
        if norm(car.get("model")) not in n:
            raise AssertionError(f"comparison: did not discuss both cars\n{reply}")
    if not any(k in n for k in ("elegiria", "escogeria", "me quedo", "empezaria por", "para ti gana", "yo iria")):
        raise AssertionError(f"comparison: Carly did not make a decision\n{reply}")
    if not any(k in n for k in ("uni", "universidad", "primer carro", "20 km", "20km")):
        raise AssertionError(f"comparison: decision was not tied back to buyer context\n{reply}")
    assert_no_unverified_certainty(reply, "comparison")
    assert_no_invented_exact_specs(reply, "comparison")
    report.append({"test": "comparison", "cars": [an, bn], "status": "PASS", "reply": reply})


def require_uncertainty(reply, label):
    n = norm(reply)
    if not any(norm(marker) in n for marker in _UNCERTAINTY_MARKERS):
        raise AssertionError(f"{label}: Carly should explicitly distinguish unknown from verified\n{reply}")


def test_unknown_facts(base_messages, recs, report):
    fav = recs[0]
    name = car_name(fav)
    questions = [
        ("airbags", f"¿El {name} tiene exactamente 6 airbags?", True),
        ("fuel_exact", f"¿Cuántos km por litro da exactamente este {name}?", True),
        ("accident_history", f"¿Este {name} ha tenido accidentes?", False),
    ]
    for key, question, ban_exact_specs in questions:
        result = followup(base_messages, recs, question)
        reply = ensure_clean_reply(result, f"unknown:{key}")
        require_uncertainty(reply, f"unknown:{key}")
        assert_no_unverified_certainty(reply, f"unknown:{key}")
        if ban_exact_specs:
            assert_no_invented_exact_specs(reply, f"unknown:{key}")
        report.append({"test": key, "car": name, "status": "PASS", "reply": reply})


def test_cartrade_next_step(base_messages, recs, report):
    fav = recs[0]
    name = car_name(fav)
    result = followup(base_messages, recs, f"¿Qué debería verificar antes de comprar el {name} y qué hago después?")
    reply = ensure_clean_reply(result, "next-step")
    n = norm(reply)
    if "cartrade" not in n:
        raise AssertionError(f"next-step: Carly did not keep CarTrade in the execution path\n{reply}")
    if not any(k in n for k in ("inspeccion", "verificacion", "kilometraje", "documentos", "papeles")):
        raise AssertionError(f"next-step: missing concrete verification guidance\n{reply}")
    banned = ("contacta al vendedor", "escribele al vendedor", "preguntale al vendedor", "llevalo a un mecanico", "busca un mecanico")
    if any(norm(x) in n for x in banned):
        raise AssertionError(f"next-step: Carly sent the buyer outside CarTrade's closing path\n{reply}")
    assert_no_unverified_certainty(reply, "next-step")
    report.append({"test": "next_step", "car": name, "status": "PASS", "reply": reply})


def assert_recommendation_constraints(result, max_km, max_price, label):
    if result.get("phase") != "recommendation":
        raise AssertionError(f"{label}: expected updated recommendation, got {result.get('phase')}: {result.get('reply')}")
    profile = result.get("profile") or {}
    if int(float(profile.get("max_km") or -1)) != int(max_km):
        raise AssertionError(f"{label}: max_km expected {max_km}, got {profile.get('max_km')}")
    if int(float(profile.get("max_price") or -1)) != int(max_price):
        raise AssertionError(f"{label}: max_price expected {max_price}, got {profile.get('max_price')}")
    for car in (result.get("recommendations") or []) + (result.get("explore") or []):
        km = car.get("km")
        price = car.get("price_usd")
        if km is None or float(km) > max_km:
            raise AssertionError(f"{label}: exposed {car_name(car)} at {km} km > {max_km}")
        if price is None or float(price) > max_price:
            raise AssertionError(f"{label}: exposed {car_name(car)} at ${price} > ${max_price}")


def test_buyer_corrections(base_messages, recs, report):
    # Raise budget while preserving the odometer ceiling.
    result = followup(
        base_messages, recs,
        "Cambio una cosa: ahora puedo llegar hasta $13,000, pero mantén el límite de 65,000 km. ¿Cambia tu recomendación?",
    )
    reply = ensure_clean_reply(result, "correction:budget")
    assert_recommendation_constraints(result, 65000, 13000, "correction:budget")
    report.append({"test": "buyer_correction_budget", "status": "PASS", "reply": reply})

    # Tighten odometer ceiling. Latest explicit buyer fact must win over history.
    result = followup(
        base_messages, recs,
        "Pensándolo bien, quiero máximo 50,000 km y sigo con máximo $12,000. Reordena tus opciones.",
    )
    reply = ensure_clean_reply(result, "correction:km")
    assert_recommendation_constraints(result, 50000, 12000, "correction:km")
    report.append({"test": "buyer_correction_km", "status": "PASS", "reply": reply})


def main():
    base_messages, initial, recs = initial_journey()
    report = []
    test_pros_cons(base_messages, recs, report)
    test_comparison(base_messages, recs, report)
    test_unknown_facts(base_messages, recs, report)
    test_cartrade_next_step(base_messages, recs, report)
    test_buyer_corrections(base_messages, recs, report)

    print(json.dumps({
        "status": "PASS",
        "initial_recommendations": [car_name(c) for c in recs],
        "tests_run": len(report),
        "results": report,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
