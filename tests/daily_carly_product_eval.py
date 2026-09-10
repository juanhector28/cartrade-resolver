from __future__ import annotations

import json
import statistics
import time
import urllib.request

BASE = "https://cartrade-resolver.onrender.com"
COUNTRY = "sv"

latencies = []
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
        headers={"Content-Type": "application/json", "User-Agent": "Carly-Daily-Product-Eval/1.0"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=70) as r:
        raw = r.read()
    dt = time.perf_counter() - t0
    latencies.append(dt)
    data = json.loads(raw.decode())
    return data, dt


def run_scenario(name, turns):
    messages = []
    last = None
    scenario_turns = []
    for user_text in turns:
        messages.append({"role": "user", "content": user_text})
        result, dt = post_chat(messages)
        reply = str(result.get("reply") or "").strip()
        scenario_turns.append({
            "user": user_text,
            "reply": reply,
            "phase": result.get("phase"),
            "profile": result.get("profile"),
            "recommendations": result.get("recommendations"),
            "explore": result.get("explore"),
            "latency_s": round(dt, 3),
        })
        messages.append({"role": "assistant", "content": reply})
        last = result
    recs = (last or {}).get("recommendations") or []
    if recs:
        a = recs[0]
        car = " ".join(str(x) for x in (a.get("make"), a.get("model"), a.get("year")) if x)
        follow = f"De estas opciones, ¿cuál comprarías tú para mí y qué debería verificar antes de avanzar con {car}?"
        messages.append({"role": "user", "content": follow})
        result, dt = post_chat(messages, shown_cars=recs)
        scenario_turns.append({
            "user": follow,
            "reply": str(result.get("reply") or "").strip(),
            "phase": result.get("phase"),
            "profile": result.get("profile"),
            "recommendations": result.get("recommendations"),
            "explore": result.get("explore"),
            "latency_s": round(dt, 3),
        })
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
    "request_count": len(latencies),
    "latency_median_s": round(statistics.median(latencies), 3) if latencies else None,
    "latency_min_s": round(min(latencies), 3) if latencies else None,
    "latency_max_s": round(max(latencies), 3) if latencies else None,
    "latencies_s": [round(x, 3) for x in latencies],
    "note": "HTTP request-to-complete-response latency from GitHub-hosted runner. Endpoint is non-streaming here, so TTFT is not separately observable.",
    "scenarios": records,
}
print("CARLY_DAILY_EVAL_JSON=" + json.dumps(summary, ensure_ascii=False))
