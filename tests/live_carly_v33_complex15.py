"""Temporary live production audit for Carly v34. Do not import into production."""
from __future__ import annotations

import concurrent.futures
import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get("CARLY_BASE_URL", "https://cartrade-resolver.onrender.com").rstrip("/")
EXPECTED = "commercial-v34-demo-safety"

CASES = [
    (1, "Toyota RAV4 2022 o más nueva, automática. Presupuesto total US$20,000 y máximo $500 al mes."),
    (2, "Honda CR-V 2024 o más nueva. Preferiría automática si se puede, máximo $500 al mes."),
    (3, "Somos 5, con un bebé, silla infantil y coche. Quiero algo cómodo para ciudad y carretera, máximo $500 al mes."),
    (4, "Voy a la finca por grava y a veces lodo. Somos 4 y llevo herramientas pesadas. Automática, máximo $550 al mes."),
    (5, "Lo usaré para delivery unos 100 km al día. Automática, presupuesto total 10 mil y máximo $250 al mes."),
    (6, "Primer carro para mi hija que va a la universidad. Seguro, fácil de parquear pero no demasiado pequeño. Automática, máximo $300 al mes."),
    (7, "Solo quiero Toyta Rav 4 2021 o más nueva y no quiero pagar más de $450 al mes."),
    (8, "Únicamente sedán automático 2022 o más nuevo. Máximo $350 al mes."),
    (9, "Solo SUV manual, 2021 o más nueva, máximo $400 al mes."),
    (10, "Honda HR-V 2023 o más nueva. No quiero manual; automática está bien. Máximo $450 al mes."),
    (11, "Busco Honda CR-V 2025 o más nueva, máximo $450 al mes. Si no hay exacta, dame alternativas parecidas."),
    (12, "Quiero una pickup pequeña para ciudad, pero necesito que 5 adultos viajen cómodos y no quiero pasar de $350 al mes."),
    (13, "No me importa la marca. Somos 4 con un bebé y viajamos seguido de San Salvador a Guatemala. Quiero confiabilidad y comodidad, máximo $500 al mes."),
    (14, "Necesito pickup 4x4 doble cabina automática para construcción, 5 pasajeros, máximo $600 al mes."),
    (15, "Carro cómodo para universidad, 20 km al día. Tengo hasta US$14,000 de contado y además no quiero una cuota mayor a $350 al mes."),
]


def get_json(path: str, timeout=20):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "CarTrade-v34-LiveAudit/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_runtime():
    for _ in range(45):
        try:
            runtime = get_json("/carly/runtime")
            if runtime.get("composition") == EXPECTED:
                print("RUNTIME_OK " + json.dumps(runtime, ensure_ascii=False, sort_keys=True))
                return runtime
            print("RUNTIME_WAIT " + json.dumps({"composition": runtime.get("composition"), "git_commit": runtime.get("git_commit")}, ensure_ascii=False))
        except Exception as exc:
            print("RUNTIME_WAIT_ERROR " + repr(exc))
        time.sleep(8)
    raise SystemExit("v34 runtime was not live before audit timeout")


def post_case(case):
    idx, prompt = case
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "country": "sv",
        "top_n": 3,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/carly/chat",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "CarTrade-v34-LiveAudit/1.0"},
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            result = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        return {"case": idx, "prompt": prompt, "http_error": exc.code, "body": text[:1200]}
    except Exception as exc:
        return {"case": idx, "prompt": prompt, "error": repr(exc)}

    def compact(card):
        return {
            "make": card.get("make"), "model": card.get("model"), "year": card.get("year"),
            "price_usd": card.get("price_usd"), "monthly_est": card.get("monthly_est"),
            "transmission": card.get("transmission"), "body_type": card.get("body_type"),
            "match": card.get("match") or card.get("match_score"),
            "best_for": card.get("best_for") or card.get("strategy_label"),
            "url": card.get("url"),
        }

    return {
        "case": idx,
        "prompt": prompt,
        "seconds": round(time.time() - started, 2),
        "advisor_mode": result.get("advisor_mode"),
        "phase": result.get("phase"),
        "reply": result.get("reply") or result.get("message") or result.get("assistant_message"),
        "brain": result.get("recommendation_brain"),
        "recommendations": [compact(x) for x in (result.get("recommendations") or [])[:3]],
        "explore": [compact(x) for x in (result.get("explore") or [])[:5]],
    }


def main():
    wait_runtime()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(post_case, c): c[0] for c in CASES}
        for fut in concurrent.futures.as_completed(futures):
            result = fut.result()
            results.append(result)
            print("CARLY_V34_COMPLEX_CASE " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    results.sort(key=lambda x: x["case"])
    print("CARLY_V34_COMPLEX_SUMMARY " + json.dumps(results, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
