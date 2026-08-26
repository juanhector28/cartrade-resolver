"""Comprehensive live evaluator for Carly after the shortlist.

Unlike the first version, this runs every independent follow-up it can and reports
all failures at the end. It evaluates buyer-objective behavior, not API health.
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
        headers={"Content-Type": "application/json", "User-Agent": "CarTrade-Carly-Followup-Eval/2.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=50) as response:
        return json.loads(response.read().decode("utf-8"))


def norm(text):
    s = str(text or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def digits(text):
    return re.sub(r"\D", "", str(text or ""))


def car_name(car):
    return " ".join(str(x) for x in (car.get("make"), car.get("model"), car.get("year")) if x)


def visible_reply(result, label):
    if not isinstance(result, dict):
        raise AssertionError(f"{label}: response is not an object")
    reply = str(result.get("reply") or "").strip()
    if not reply:
        raise AssertionError(f"{label}: empty reply")
    if "[DIAG]" in reply:
        raise AssertionError(f"{label}: diagnostic text leaked")
    if "<PROFILE>" in reply.upper():
        raise AssertionError(f"{label}: internal PROFILE protocol leaked")
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
    for text in turns:
        messages.append({"role": "user", "content": text})
        result = post_chat(messages)
        reply = visible_reply(result, f"initial:{text}")
        messages.append({"role": "assistant", "content": reply})

    if result.get("phase") != "recommendation":
        raise AssertionError(
            "Carly had enough information after $12k but did not recommend: "
            + str(result.get("reply"))
        )
    profile = result.get("profile") or {}
    if int(float(profile.get("max_km") or -1)) != 65000:
        raise AssertionError(f"initial max_km drifted: {profile.get('max_km')}")
    if int(float(profile.get("max_price") or -1)) != 12000:
        raise AssertionError(f"initial max_price drifted: {profile.get('max_price')}")
    if abs(float(profile.get("daily_km") or -1) - 20) > 0.01:
        raise AssertionError(f"initial daily_km drifted: {profile.get('daily_km')}")
    recs = result.get("recommendations") or []
    if len(recs) < 3:
        raise AssertionError(f"expected at least 3 curated recommendations, got {len(recs)}")
    return messages, recs


ABSOLUTE_UNIT_CLAIMS = (
    "no te va a dar dolores de cabeza", "no te dara dolores de cabeza",
    "no te va a dar problemas", "no te dara problemas", "esta en buen estado",
    "esta limpia", "esta impecable", "sin problemas mecanicos",
    "sin problemas de documentos",
)
EXACT_SPEC_PATTERNS = (
    re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:km/l|km por litro|l/100\s*km)\b", re.I),
    re.compile(r"\b\d+\s*(?:hp|caballos(?: de fuerza)?)\b", re.I),
    re.compile(r"\b\d+\s+airbags?\b", re.I),
)
SPECULATIVE_MECHANICAL_PATTERNS = (
    re.compile(r"manual.{0,100}(?:consume\s+menos|ahorra\s+gasolina|mas\s+economico\s+en\s+combustible)", re.I | re.S),
    re.compile(r"manual.{0,120}(?:mantenimiento|caja).{0,80}mas\s+barat", re.I | re.S),
    re.compile(r"(?:muchos|varios)\s+años?.{0,80}(?:mantenimiento|reparacion|reparación)\s+mayor", re.I | re.S),
)
UNKNOWN_MARKERS = (
    "no tengo", "no aparece", "no esta en los datos", "no esta reportado",
    "no puedo confirmar", "no puedo verificar", "no esta confirmado",
    "hay que verificar", "requiere verificacion", "la inspeccion", "verificarlo",
)
CAVEAT_MARKERS = (
    "preocupa", "en contra", "contra", "ojo", "verificar", "reportado",
    "no esta confirmado", "trade-off", "tradeoff", "pero", "limitacion", "limitación",
)
BUYER_CONTEXT_MARKERS = (
    "primer carro", "primer auto", "uni", "universidad", "20 km", "20km",
    "65,000", "65k", "$12,000", "$12k", "presupuesto",
)


def assert_safe_claims(reply, label):
    n = norm(reply)
    for phrase in ABSOLUTE_UNIT_CLAIMS:
        if norm(phrase) in n:
            raise AssertionError(f"{label}: unsupported unit certainty: {phrase}")
    for pattern in EXACT_SPEC_PATTERNS:
        match = pattern.search(reply)
        if match:
            raise AssertionError(f"{label}: exact spec invented or ungrounded: {match.group(0)}")
    for pattern in SPECULATIVE_MECHANICAL_PATTERNS:
        match = pattern.search(n)
        if match:
            raise AssertionError(f"{label}: speculative mechanical claim: {match.group(0)}")


def assert_percentage_grounded(reply, car, label):
    found = [float(x.replace(",", ".")) for x in re.findall(r"\b(\d+(?:[.,]\d+)?)\s*%", reply)]
    if not found:
        return
    allowed = []
    for key in ("value_delta_pct", "match_pct"):
        value = car.get(key)
        if isinstance(value, (int, float)):
            allowed.append(abs(float(value)))
    for pct in found:
        if pct == 100:
            continue
        if not any(abs(pct - expected) <= 1.0 for expected in allowed):
            raise AssertionError(f"{label}: ungrounded percentage {pct}%; expected one of {allowed}")


def contains_number(reply, value):
    if value is None:
        return False
    target = digits(round(float(value)))
    return bool(target and target in digits(reply))


def followup(base_messages, recs, text):
    messages = list(base_messages) + [{"role": "user", "content": text}]
    return post_chat(messages, shown_cars=recs)


def check_pros_cons(base_messages, recs, car):
    name = car_name(car)
    result = followup(
        base_messages, recs,
        f"Cuéntame más del {name}: ¿por qué me lo recomiendas y qué debería preocuparme?",
    )
    reply = visible_reply(result, f"pros_cons:{name}")
    n = norm(reply)
    if result.get("phase") != "conversation":
        raise AssertionError(f"follow-up restarted recommendation flow: {result.get('phase')}")
    if norm(car.get("model")) not in n or str(car.get("year") or "") not in reply:
        raise AssertionError("did not stay anchored to the requested vehicle")
    if not (contains_number(reply, car.get("km")) or contains_number(reply, car.get("price_usd"))):
        raise AssertionError("did not use a concrete fact from this unit")
    if not any(norm(x) in n for x in BUYER_CONTEXT_MARKERS):
        raise AssertionError("did not tie advice back to this buyer")
    if not any(norm(x) in n for x in CAVEAT_MARKERS):
        raise AssertionError("did not provide an honest downside or verification point")
    if "no te lo recomende" in n or "no lo recomende" in n:
        raise AssertionError("denied a car that Carly herself curated")
    assert_safe_claims(reply, f"pros_cons:{name}")
    assert_percentage_grounded(reply, car, f"pros_cons:{name}")
    return reply


def check_comparison(base_messages, recs):
    a, b = recs[0], recs[1]
    result = followup(
        base_messages, recs,
        f"Entre el {car_name(a)} y el {car_name(b)}, ¿cuál escogerías para mí y por qué?",
    )
    reply = visible_reply(result, "comparison")
    n = norm(reply)
    if result.get("phase") != "conversation":
        raise AssertionError("comparison restarted recommendation flow")
    if norm(a.get("model")) not in n or norm(b.get("model")) not in n:
        raise AssertionError("comparison did not discuss both requested cars")
    if not any(x in n for x in ("elegiria", "escogeria", "me quedo", "empezaria por", "para ti", "yo iria")):
        raise AssertionError("Carly did not take a position")
    if not any(norm(x) in n for x in BUYER_CONTEXT_MARKERS):
        raise AssertionError("decision was not personalized to the buyer")
    assert_safe_claims(reply, "comparison")
    return reply


def check_unknown(base_messages, recs, key, question):
    result = followup(base_messages, recs, question)
    reply = visible_reply(result, f"unknown:{key}")
    n = norm(reply)
    if result.get("phase") != "conversation":
        raise AssertionError("unknown-fact question restarted recommendation flow")
    if not any(norm(x) in n for x in UNKNOWN_MARKERS):
        raise AssertionError("Carly did not explicitly distinguish unknown from verified")
    assert_safe_claims(reply, f"unknown:{key}")
    return reply


def check_next_step(base_messages, recs):
    fav = recs[0]
    result = followup(
        base_messages, recs,
        f"¿Qué debería verificar antes de comprar el {car_name(fav)} y qué hago después?",
    )
    reply = visible_reply(result, "next_step")
    n = norm(reply)
    if result.get("phase") != "conversation":
        raise AssertionError("next-step question restarted recommendation flow")
    if "cartrade" not in n:
        raise AssertionError("Carly dropped CarTrade from the execution path")
    if not any(x in n for x in ("inspeccion", "verificacion", "kilometraje", "documentos", "papeles")):
        raise AssertionError("missing concrete verification guidance")
    for banned in ("contacta al vendedor", "escribele al vendedor", "preguntale al vendedor", "llevalo a un mecanico", "busca un mecanico"):
        if norm(banned) in n:
            raise AssertionError("sent buyer outside CarTrade's closing path")
    assert_safe_claims(reply, "next_step")
    return reply


def assert_updated_recommendation(result, max_km, max_price, label):
    reply = visible_reply(result, label)
    if result.get("phase") != "recommendation":
        raise AssertionError(f"criteria change did not rerank: {result.get('phase')} | {reply}")
    profile = result.get("profile") or {}
    if int(float(profile.get("max_km") or -1)) != max_km:
        raise AssertionError(f"max_km should be {max_km}, got {profile.get('max_km')}")
    if int(float(profile.get("max_price") or -1)) != max_price:
        raise AssertionError(f"max_price should be {max_price}, got {profile.get('max_price')}")
    for car in (result.get("recommendations") or []) + (result.get("explore") or []):
        if car.get("km") is None or float(car["km"]) > max_km:
            raise AssertionError(f"{car_name(car)} violates max_km: {car.get('km')}")
        if car.get("price_usd") is None or float(car["price_usd"]) > max_price:
            raise AssertionError(f"{car_name(car)} violates max_price: {car.get('price_usd')}")
    return reply


def run_case(results, failures, name, fn):
    try:
        reply = fn()
        results.append({"test": name, "status": "PASS", "reply": reply})
    except Exception as exc:
        failures.append({"test": name, "error": str(exc)})
        results.append({"test": name, "status": "FAIL", "error": str(exc)})


def main():
    try:
        base_messages, recs = initial_journey()
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "stage": "initial_journey", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise AssertionError(str(exc))

    results, failures = [], []

    for car in recs:
        run_case(results, failures, f"pros_cons:{car_name(car)}", lambda car=car: check_pros_cons(base_messages, recs, car))

    run_case(results, failures, "comparison_top2", lambda: check_comparison(base_messages, recs))

    fav = recs[0]
    name = car_name(fav)
    run_case(results, failures, "unknown_airbags", lambda: check_unknown(base_messages, recs, "airbags", f"¿El {name} tiene exactamente 6 airbags?"))
    run_case(results, failures, "unknown_fuel_economy", lambda: check_unknown(base_messages, recs, "fuel", f"¿Cuántos km por litro da exactamente este {name}?"))
    run_case(results, failures, "unknown_accident_history", lambda: check_unknown(base_messages, recs, "accident", f"¿Este {name} ha tenido accidentes?"))
    run_case(results, failures, "cartrade_next_step", lambda: check_next_step(base_messages, recs))

    def budget_change():
        result = followup(base_messages, recs, "Cambio una cosa: ahora puedo llegar hasta $13,000, pero mantén el límite de 65,000 km. ¿Cambia tu recomendación?")
        return assert_updated_recommendation(result, 65000, 13000, "budget_change")

    def km_change():
        result = followup(base_messages, recs, "Pensándolo bien, quiero máximo 50,000 km y sigo con máximo $12,000. Reordena tus opciones.")
        return assert_updated_recommendation(result, 50000, 12000, "km_change")

    run_case(results, failures, "buyer_changes_budget", budget_change)
    run_case(results, failures, "buyer_tightens_km", km_change)

    report = {
        "status": "FAIL" if failures else "PASS",
        "recommendations_tested": [car_name(c) for c in recs],
        "tests_run": len(results),
        "passed": sum(1 for x in results if x["status"] == "PASS"),
        "failed": len(failures),
        "failures": failures,
        "results": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise AssertionError(f"{len(failures)} follow-up quality tests failed")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
