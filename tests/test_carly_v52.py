import os
from types import SimpleNamespace

os.environ.setdefault("CACHE_DB", "/tmp/carly-v52-cache.db")
os.environ.setdefault("TRUSTPLUS_DB", "/tmp/carly-v52-trustplus.db")
os.environ.setdefault("CARLY_VISION_JIT_ENABLED", "0")

from app import main_v14 as v14
from app import main_v52 as v52


def test_unstated_daily_km_is_removed_from_reply():
    buyer = "Busco un Mazda SUV entre USD 12,000 y 25,000"
    reply = "Entendido, buscas un Mazda SUV; y ya sé que manejas unos 100 km al día en Ciudad de Guatemala. ¿Para qué lo vas a usar principalmente?"
    out = v52._strip_unstated_daily_km(reply, buyer)
    assert "100 km" not in out
    assert "¿Para qué lo vas a usar principalmente?" in out


def test_explicit_daily_km_is_preserved():
    buyer = "Manejo unos 35 km al día para ir al trabajo"
    reply = "Entendido, ya sé que manejas unos 35 km al día. ¿Qué cuota te queda cómoda?"
    assert v52._strip_unstated_daily_km(reply, buyer) == reply


def test_cx30_guidance_is_specific_and_comparative():
    g = v52._cx_guidance({"make": "Mazda", "model": "CX-30", "body_type": "suv"})
    assert "CX-5" in g["pros"] or "CX-5" in g["cons"]
    assert "espacio" in g["cons"].lower()
    assert "precio y disponibilidad" not in g["pros"].lower()


def test_vehicle_brief_uses_real_visible_tradeoff():
    body = SimpleNamespace(
        country="gt",
        messages=[
            {"role": "user", "content": "Busco un Mazda SUV entre USD 12,000 y 25,000"},
            {"role": "assistant", "content": "¿Para qué lo vas a usar principalmente?"},
            {"role": "user", "content": "trabajo y dejar a mis hijos al colegio"},
            {"role": "assistant", "content": "¿Qué cuota mensual te queda cómoda?"},
            {"role": "user", "content": "550 al mes"},
            {"role": "user", "content": "Cuéntame más del Mazda CX-30 2024: ¿por qué me lo recomiendas y qué debería preocuparme?"},
        ],
        shown_cars=[
            {"url":"https://x/cx30","make":"Mazda","model":"CX-30","year":2024,"km":31741,"monthly_est":494,"price_usd":20900,"body_type":"suv"},
            {"url":"https://x/cx5","make":"Mazda","model":"CX-5","year":2024,"km":48000,"monthly_est":540,"price_usd":22800,"body_type":"suv"},
        ],
    )
    out = v14._advisor_brief(body)
    assert out is not None
    text = out["reply"]
    assert "$494/mes" in text
    assert "$540/mes" in text or "31,741 km" in text
    assert "espacio trasero" in text
    assert "precio y disponibilidad" not in text.lower()
    assert "familia de cinco" not in text.lower()


def test_v52_truth_guard_is_outermost():
    route = next(r for r in v52.app.routes if getattr(r, "path", None) == "/carly/chat")
    assert getattr(route.endpoint, "_carly_v52_truth_guard", False) is True
