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


def post_chat(messages, shown_cars=None, top_n=6):
    payload = json.dumps({
        "messages": messages,
        "country": COUNTRY,
        "top_n": top_n,
        "shown_cars": shown_cars or None,
    }).encode()
    req = urllib.request.Request(
        BASE + "/carly/chat",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Carly-Daily-Product-Eval/1.1"},
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


def emit_turn(scenario, user_text, result, dt, error=None):
    row = {
        "scenario": scenario,
        "user": user_text,
        "latency_s": round(dt, 3),
        "completed": error is None,
        "error": error,
    }
    if result:
        row.update({
            "reply": str(result.get("reply") or "").strip(),
            "phase": result.get("phase"),
            "profile": result.get("profile"),
            "recommendations": result.get("recommendations"),
            "explore": result.get("explore"),
        })
    print("CARLY_EVAL_TURN=" + json.dumps(row, ensure_ascii=False), flush=True)
    return row


def run_scenario(name, turns):
    messages = []
    last = None
    scenario_turns = []
    for user_text in turns:
        messages.append({"role": "user", "content": user_text})
        result, dt, error = post_chat(messages)
        row = emit_turn(name, user_text, result, dt, error)
        scenario_turns.append(row)
        if error:
            break
        reply = row["reply"]
        messages.append({"role": "assistant", "content": reply})
        last = result
    recs = (last or {}).get("recommendations") or []
    if recs:
        a = recs[0]
        car = " ".join(str(x) for x in (a.get("make"), a.get("model"), a.get("year")) if x)
        follow = f"De estas opciones, ¿cuál comprarías tú para mí y qué debería verificar antes de avanzar con {car}?"
        messages.append({"role": "user", "content": follow})
        result, dt, error = post_chat(messages, shown_cars=recs)
        scenario_turns.append(emit_turn(name, follow, result, dt, error))
    records.append({"scenario": name, "turns": scenario_turns})


run_scenario("first_car_university", [
    "Es mi primer carro y lo usaría para ir a la universidad. No quiero pasar de 65,000 km.",
    "Hago unos 20 km diarios y quiero algo económico de mantener.",
    "Mi máximo son $12,000.",
])

run_scenario("young_family_automatic", [
    "Busco carro para mi esposa, nuestro bebé y yo. Principalmente ciudad, pero hacemos carretera algunos fines de semana.",
    "Automático sí o sí. Me importa que sea práctico, seguro y que no sea un dolor de cabeza.",
    "Puedo gastar hasta $16,000. No necesito SUV si hay algo mejor para nosotros.",
])

run_scenario("soft_toyota_preference_value", [
    "Quiero gastar máximo $11,000 y máximo 80,000 km. Preferiría Toyota, pero si otra marca me conviene claramente más, dímelo.",
    "Lo usaré unos 30 km diarios. Quiero el mejor valor total, no solo el más barato.",
])

summary = {
    "completed_request_count": len(completed_latencies),
    "attempted_request_count": len(observed_latencies),
    "timeout_s": TIMEOUT_S,
    "latency_median_completed_s": round(statistics.median(completed_latencies), 3) if completed_latencies else None,
    "latency_min_completed_s": round(min(completed_latencies), 3) if completed_latencies else None,
    "latency_max_completed_s": round(max(completed_latencies), 3) if completed_latencies else None,
    "completed_latencies_s": [round(x, 3) for x in completed_latencies],
    "all_attempt_durations_s": [round(x, 3) for x in observed_latencies],
    "note": "HTTP request-to-complete-response latency from GitHub-hosted runner. Non-streaming measurement: TTFT is not separately observable. Timeout attempts are excluded from completed-response median and reported separately.",
    "scenarios": records,
}
print("CARLY_DAILY_EVAL_JSON=" + json.dumps(summary, ensure_ascii=False), flush=True)
