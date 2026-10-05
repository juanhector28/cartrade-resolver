from __future__ import annotations

import json
import re
import statistics
import time
import urllib.request

BASE = "https://cartrade-resolver.onrender.com"
COUNTRY = "sv"
TIMEOUT_S = 45

SCENARIOS = [
    {
        "name": "first_car_university",
        "turns": [
            "Es mi primer carro y lo usaría para ir a la universidad. No quiero pasar de 65,000 km.",
            "Hago unos 20 km diarios y quiero algo económico de mantener.",
            "Mi máximo son $12,000.",
        ],
        "expect": {"max_price": 12000, "max_km": 65000},
    },
    {
        "name": "typed_budget_odometer_soft_brand",
        "turns": [
            "Quiero gastar máximo $11,000 y máximo 80,000 km. Preferiría Toyota, pero si otra marca me conviene claramente más, dímelo.",
            "Lo usaré unos 30 km diarios. Quiero el mejor valor total, no solo el más barato.",
        ],
        "expect": {"max_price": 11000, "max_km": 80000},
    },
    {
        "name": "young_family_automatic",
        "turns": [
            "Busco carro para mi esposa, nuestro bebé y yo. Principalmente ciudad, pero hacemos carretera algunos fines de semana.",
            "Automático sí o sí. Me importa que sea práctico, seguro y que no sea un dolor de cabeza.",
            "Puedo gastar hasta $16,000. No necesito SUV si hay algo mejor para nosotros.",
        ],
        "expect": {"max_price": 16000, "automatic": True},
    },
    {
        "name": "hard_budget_no_relaxation",
        "turns": [
            "Necesito un carro confiable para ir al trabajo. Máximo $9,500 y ese presupuesto no lo puedo subir.",
            "Hago alrededor de 35 km diarios. Prefiero automático, pero manual también me sirve si la opción es claramente mejor.",
        ],
        "expect": {"max_price": 9500},
    },
    {
        "name": "exact_model_with_fallback",
        "turns": [
            "Estoy buscando una Honda CR-V 2023 o más nueva, automática, máximo $20,000. Si no hay una exacta, dime claramente y luego enséñame alternativas similares.",
        ],
        "expect": {"max_price": 20000, "automatic": True, "min_year": 2023},
    },
    {
        "name": "delivery_economy",
        "turns": [
            "Lo quiero para delivery todos los días, unos 70 km diarios. Quiero gastar máximo $10,500 y priorizo consumo y mantenimiento.",
        ],
        "expect": {"max_price": 10500},
    },
]

latencies: list[float] = []
rows: list[dict] = []


def get_json(path: str):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read().decode())


def post_chat(messages, shown_cars=None):
    payload = json.dumps({
        "messages": messages,
        "country": COUNTRY,
        "top_n": 6,
        "shown_cars": shown_cars or None,
    }).encode()
    req = urllib.request.Request(
        BASE + "/carly/chat",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Carly-Product-Benchmark-v2"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            raw = r.read()
        dt = time.perf_counter() - t0
        latencies.append(dt)
        return json.loads(raw.decode()), dt, None
    except Exception as exc:
        dt = time.perf_counter() - t0
        latencies.append(dt)
        return None, dt, f"{type(exc).__name__}: {exc}"


def num(v):
    try:
        return float(v)
    except Exception:
        return None


def transmission(card):
    return str(card.get("transmission") or "").lower()


def constraint_violations(result, expect):
    out = []
    cards = list(result.get("recommendations") or []) + list(result.get("explore") or [])
    for card in cards:
        p, km, year = num(card.get("price_usd")), num(card.get("km")), num(card.get("year"))
        if expect.get("max_price") is not None and (p is None or p > expect["max_price"]):
            out.append(f"price:{card.get('make')} {card.get('model')}={p}")
        if expect.get("max_km") is not None and (km is None or km > expect["max_km"]):
            out.append(f"km:{card.get('make')} {card.get('model')}={km}")
        if expect.get("min_year") is not None and (year is None or year < expect["min_year"]):
            out.append(f"year:{card.get('make')} {card.get('model')}={year}")
        if expect.get("automatic") and "auto" not in transmission(card):
            out.append(f"transmission:{card.get('make')} {card.get('model')}={card.get('transmission')}")
    return out


def profile_violations(result, expect):
    p = result.get("profile") or {}
    out = []
    for k in ("max_price", "max_km", "min_year"):
        if expect.get(k) is not None:
            actual = num(p.get(k))
            if actual is None or int(actual) != int(expect[k]):
                out.append(f"profile_{k}:{actual}!= {expect[k]}")
    return out


def dominates(a, b):
    # Conservative: only compare same body/transmission and fully-known price/km/year.
    if str(a.get("body_type") or "").lower() != str(b.get("body_type") or "").lower():
        return False
    if transmission(a) != transmission(b):
        return False
    ap, ak, ay = num(a.get("price_usd")), num(a.get("km")), num(a.get("year"))
    bp, bk, by = num(b.get("price_usd")), num(b.get("km")), num(b.get("year"))
    if None in (ap, ak, ay, bp, bk, by):
        return False
    not_worse = ap <= bp and ak <= bk and ay >= by
    strictly = ap < bp or ak < bk or ay > by
    return not_worse and strictly


def dominance_misses(result):
    recs = list(result.get("recommendations") or [])
    explore = list(result.get("explore") or [])
    misses = []
    for r in recs:
        for e in explore:
            if dominates(e, r):
                misses.append({
                    "recommended": f"{r.get('make')} {r.get('model')} {r.get('year')}",
                    "dominated_by": f"{e.get('make')} {e.get('model')} {e.get('year')}",
                })
    return misses


def grounding_flags(reply, visible):
    # Conservative numeric grounding check: percentages in the prose must come from
    # visible structured match/value fields.
    allowed = set()
    for car in visible:
        for k in ("match_pct", "value_delta_pct"):
            v = num(car.get(k))
            if v is not None:
                allowed.add(round(abs(v), 1))
    flags = []
    for raw in re.findall(r"\b(\d+(?:[.,]\d+)?)\s*%", reply or ""):
        v = round(float(raw.replace(",", ".")), 1)
        if v != 100.0 and all(abs(v - x) > 1.0 for x in allowed):
            flags.append(f"ungrounded_percentage:{v}")
    return flags


def closing_ok(reply):
    n = (reply or "").lower()
    return any(x in n for x in ("inspe", "verific", "cartrade", "avanz", "reserv", "compra"))


runtime = get_json("/carly/runtime")
print("CARLY_BENCHMARK_RUNTIME=" + json.dumps(runtime, ensure_ascii=False), flush=True)

scenario_scores = []
for scenario in SCENARIOS:
    messages = []
    last = None
    completed = 0
    recommendation_turn = None
    turn_rows = []
    for idx, text in enumerate(scenario["turns"], 1):
        messages.append({"role": "user", "content": text})
        result, dt, error = post_chat(messages)
        row = {"turn": idx, "user": text, "latency_s": round(dt, 3), "error": error}
        if result:
            row["phase"] = result.get("phase")
            row["reply"] = result.get("reply")
            row["profile"] = result.get("profile")
            row["recommendation_count"] = len(result.get("recommendations") or [])
            if result.get("phase") == "recommendation" and recommendation_turn is None:
                recommendation_turn = idx
            last = result
            messages.append({"role": "assistant", "content": str(result.get("reply") or "")})
            completed += 1
        turn_rows.append(row)
        if error:
            break

    expect = scenario["expect"]
    hard = profile_violations(last or {}, expect) + constraint_violations(last or {}, expect)
    dom = dominance_misses(last or {})
    visible = list((last or {}).get("recommendations") or []) + list((last or {}).get("explore") or [])
    grounding = grounding_flags(str((last or {}).get("reply") or ""), visible)

    follow_result = None
    follow_latency = None
    if (last or {}).get("recommendations"):
        follow = "¿Cuál comprarías tú para mí, qué trade-off estoy aceptando y qué verificarías antes de avanzar?"
        messages.append({"role": "user", "content": follow})
        follow_result, follow_latency, follow_error = post_chat(messages, shown_cars=(last or {}).get("recommendations"))
        turn_rows.append({
            "turn": "followup",
            "user": follow,
            "latency_s": round(follow_latency, 3),
            "error": follow_error,
            "reply": (follow_result or {}).get("reply"),
        })

    need_score = 15 if recommendation_turn is not None and recommendation_turn <= len(scenario["turns"]) else 8
    inference_score = 15 if recommendation_turn is not None and recommendation_turn <= 2 else (10 if recommendation_turn else 5)
    candidate_score = 20 if not dom and (last or {}).get("recommendations") else (10 if (last or {}).get("recommendations") else 0)
    constraint_score = 15 if not hard else 0
    grounding_score = 15 if not grounding else 5
    closing_score = 10 if follow_result and closing_ok(str(follow_result.get("reply") or "")) else 4
    scenario_latency = [r["latency_s"] for r in turn_rows if isinstance(r.get("latency_s"), (int, float))]
    perf_med = statistics.median(scenario_latency) if scenario_latency else TIMEOUT_S
    perf_score = 10 if perf_med <= 4 else (7 if perf_med <= 8 else (3 if perf_med <= 20 else 0))
    score = need_score + inference_score + candidate_score + constraint_score + grounding_score + closing_score + perf_score

    verdict = {
        "scenario": scenario["name"],
        "score": score,
        "hard_fail": bool(hard or grounding),
        "recommendation_turn": recommendation_turn,
        "constraint_violations": hard,
        "dominance_misses": dom,
        "grounding_flags": grounding,
        "closing_ok": bool(follow_result and closing_ok(str(follow_result.get("reply") or ""))),
        "turns": turn_rows,
    }
    scenario_scores.append(verdict)
    print("CARLY_BENCHMARK_SCENARIO=" + json.dumps(verdict, ensure_ascii=False), flush=True)

completed = [x for x in latencies if x < TIMEOUT_S]
summary = {
    "runtime": runtime,
    "score_general": round(sum(x["score"] for x in scenario_scores) / len(scenario_scores), 1),
    "hard_fail_scenarios": [x["scenario"] for x in scenario_scores if x["hard_fail"]],
    "latency_median_s": round(statistics.median(completed), 3) if completed else None,
    "latency_range_s": [round(min(completed), 3), round(max(completed), 3)] if completed else None,
    "timeout_count": sum(1 for x in latencies if x >= TIMEOUT_S),
    "attempt_count": len(latencies),
    "ttft_observable": False,
    "candidate_quality_scope": "loaded recommendation+explore set; not full Atlas market universe",
    "scenarios": scenario_scores,
}
print("CARLY_PRODUCT_BENCHMARK_V2=" + json.dumps(summary, ensure_ascii=False), flush=True)
