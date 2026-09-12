from __future__ import annotations

import json
import statistics
import time
import urllib.request

BASE = "https://cartrade-resolver.onrender.com"
COUNTRY = "sv"
TIMEOUT_S = 45

completed_latencies = []
observed_latencies = []
records = []
hard_failures = []
quality_flags = []


def num(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def post_chat(messages, shown_cars=None, top_n=12):
    payload = json.dumps({
        "messages": messages,
        "country": COUNTRY,
        "top_n": top_n,
        "shown_cars": shown_cars or None,
    }).encode()
    req = urllib.request.Request(
        BASE + "/carly/chat",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Carly-Product-Benchmark/2.0"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            raw = r.read()
        dt = time.perf_counter() - t0
        completed_latencies.append(dt)
        observed_latencies.append(dt)
        return json.loads(raw.decode()), dt, None
    except Exception as exc:
        dt = time.perf_counter() - t0
        observed_latencies.append(dt)
        return None, dt, f"{type(exc).__name__}: {exc}"


def violations(result, expected):
    out = []
    profile = (result or {}).get("profile") or {}
    recs = (result or {}).get("recommendations") or []
    max_price, max_km = expected.get("max_price"), expected.get("max_km")

    if max_price is not None and profile.get("max_price") is not None:
        if num(profile.get("max_price")) != float(max_price):
            out.append(f"profile.max_price={profile.get('max_price')} expected={max_price}")
    if max_km is not None and profile.get("max_km") is not None:
        if num(profile.get("max_km")) != float(max_km):
            out.append(f"profile.max_km={profile.get('max_km')} expected={max_km}")

    for car in recs:
        price, km = num(car.get("price_usd")), num(car.get("km"))
        name = " ".join(str(x) for x in (car.get("make"), car.get("model"), car.get("year")) if x)
        if max_price is not None and (price is None or price > max_price):
            out.append(f"{name}: price={price} > {max_price}")
        if max_km is not None and (km is None or km > max_km):
            out.append(f"{name}: km={km} > {max_km}")
    return out


def dominance_flags(result):
    recs = (result or {}).get("recommendations") or []
    universe = recs + ((result or {}).get("explore") or [])
    flags = []
    for chosen in recs:
        cp, ck, cy = num(chosen.get("price_usd")), num(chosen.get("km")), num(chosen.get("year"))
        if None in (cp, ck, cy):
            continue
        cb = str(chosen.get("body_type") or "").lower()
        ct = str(chosen.get("transmission") or "").lower()
        for alt in universe:
            if alt is chosen:
                continue
            ap, ak, ay = num(alt.get("price_usd")), num(alt.get("km")), num(alt.get("year"))
            if None in (ap, ak, ay):
                continue
            if cb and str(alt.get("body_type") or "").lower() != cb:
                continue
            if ct and str(alt.get("transmission") or "").lower() != ct:
                continue
            if ap <= cp and ak <= ck and ay >= cy and (ap < cp or ak < ck or ay > cy):
                flags.append({
                    "recommended": [chosen.get("make"), chosen.get("model"), chosen.get("year")],
                    "dominant_visible_candidate": [alt.get("make"), alt.get("model"), alt.get("year")],
                })
                break
    return flags


def emit_turn(scenario, user_text, result, dt, error=None, expected=None):
    v = violations(result, expected or {}) if result else []
    q = dominance_flags(result) if result else []
    row = {
        "scenario": scenario,
        "user": user_text,
        "latency_s": round(dt, 3),
        "completed": error is None,
        "error": error,
        "hard_constraint_violations": v,
        "surface_dominance_flags": q,
    }
    if result:
        row.update({
            "reply": str(result.get("reply") or "").strip(),
            "phase": result.get("phase"),
            "profile": result.get("profile"),
            "recommendations": result.get("recommendations"),
            "explore": result.get("explore"),
        })
    hard_failures.extend(f"{scenario}: {x}" for x in v)
    quality_flags.extend({"scenario": scenario, **x} for x in q)
    print("CARLY_EVAL_TURN=" + json.dumps(row, ensure_ascii=False), flush=True)
    return row


def run_scenario(name, turns, expected):
    messages, scenario_turns = [], []
    last = None
    for user_text in turns:
        messages.append({"role": "user", "content": user_text})
        result, dt, error = post_chat(messages)
        row = emit_turn(name, user_text, result, dt, error, expected)
        scenario_turns.append(row)
        if error:
            break
        messages.append({"role": "assistant", "content": row["reply"]})
        last = result

    recs = (last or {}).get("recommendations") or []
    if recs:
        a = recs[0]
        car = " ".join(str(x) for x in (a.get("make"), a.get("model"), a.get("year")) if x)
        follow = f"De estas opciones, ¿cuál comprarías tú para mí y qué debería verificar antes de avanzar con {car}?"
        messages.append({"role": "user", "content": follow})
        result, dt, error = post_chat(messages, shown_cars=recs)
        scenario_turns.append(emit_turn(name, follow, result, dt, error, expected))

    records.append({"scenario": name, "turns": scenario_turns})


run_scenario("first_car_university", [
    "Es mi primer carro y lo usaría para ir a la universidad. No quiero pasar de 65,000 km.",
    "Hago unos 20 km diarios y quiero algo económico de mantener.",
    "Mi máximo son $12,000.",
], {"max_price": 12000, "max_km": 65000})

run_scenario("young_family_automatic", [
    "Busco carro para mi esposa, nuestro bebé y yo. Principalmente ciudad, pero hacemos carretera algunos fines de semana.",
    "Automático sí o sí. Me importa que sea práctico, seguro y que no sea un dolor de cabeza.",
    "Puedo gastar hasta $16,000. No necesito SUV si hay algo mejor para nosotros.",
], {"max_price": 16000})

run_scenario("soft_toyota_preference_value", [
    "Quiero gastar máximo $11,000 y máximo 80,000 km. Preferiría Toyota, pero si otra marca me conviene claramente más, dímelo.",
    "Lo usaré unos 30 km diarios. Quiero el mejor valor total, no solo el más barato.",
], {"max_price": 11000, "max_km": 80000})

completed, attempted = len(completed_latencies), len(observed_latencies)
summary = {
    "benchmark_version": 2,
    "completed_request_count": completed,
    "attempted_request_count": attempted,
    "timeout_count": attempted - completed,
    "timeout_s": TIMEOUT_S,
    "latency_median_completed_s": round(statistics.median(completed_latencies), 3) if completed_latencies else None,
    "latency_min_completed_s": round(min(completed_latencies), 3) if completed_latencies else None,
    "latency_max_completed_s": round(max(completed_latencies), 3) if completed_latencies else None,
    "completed_latencies_s": [round(x, 3) for x in completed_latencies],
    "all_attempt_durations_s": [round(x, 3) for x in observed_latencies],
    "hard_failure_count": len(hard_failures),
    "hard_failures": hard_failures,
    "candidate_quality_flag_count": len(quality_flags),
    "candidate_quality_flags": quality_flags,
    "note": "Request-to-complete-response latency from GitHub-hosted runner. TTFT is not separately observable because /carly/chat is non-streaming. Surface dominance is diagnostic, not an automatic failure.",
    "scenarios": records,
}
print("CARLY_DAILY_EVAL_JSON=" + json.dumps(summary, ensure_ascii=False), flush=True)

if hard_failures:
    raise SystemExit("Hard buyer-constraint violation: " + " | ".join(hard_failures))
