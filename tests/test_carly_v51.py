import os
from types import SimpleNamespace

os.environ.setdefault("CACHE_DB", "/tmp/carly-v51-cache.db")
os.environ.setdefault("TRUSTPLUS_DB", "/tmp/carly-v51-trustplus.db")
os.environ.setdefault("CARLY_VISION_JIT_ENABLED", "0")

from app import main_v14 as v14
from app import main_v51 as v51


def _family_constraints(passengers=None):
    return {
        "exact": None,
        "intent": {
            "heavy_cargo": False,
            "farm": False,
            "rough": False,
            "student": False,
            "comfort": False,
        },
        "family": True,
        "passengers": passengers,
        "delivery": False,
        "require_body": None,
        "require_transmission": None,
    }


def test_family_intent_without_explicit_size_never_claims_five():
    reply = v51._truthful_reply(_family_constraints(), [])
    assert "familia de cinco" not in reply.lower()
    assert "uso familiar" in reply.lower()


def test_explicit_family_of_five_can_keep_five_person_wording():
    reply = v51._truthful_reply(_family_constraints(5), [])
    assert "familia de cinco" in reply.lower()


def test_exact_cx30_followup_hits_vehicle_brief_not_shortlist_reply():
    prompt = "Cuéntame más del Mazda CX-30 2023: ¿por qué me lo recomiendas y qué debería preocuparme?"
    body = SimpleNamespace(
        country="gt",
        messages=[
            {"role": "user", "content": "Busco un Mazda SUV entre USD 12,000 y 25,000"},
            {"role": "assistant", "content": "¿Para qué lo vas a usar principalmente?"},
            {"role": "user", "content": "trabajo y dejar a mis hijos al colegio"},
            {"role": "assistant", "content": "¿Qué cuota mensual te queda cómoda?"},
            {"role": "user", "content": "550 al mes"},
            {"role": "assistant", "content": "Te muestro mis mejores opciones."},
            {"role": "user", "content": prompt},
        ],
        shown_cars=[
            {
                "url": "https://example.test/mazda-cx30-2023",
                "make": "Mazda",
                "model": "CX-30",
                "year": 2023,
                "price_usd": 22000,
                "monthly_est": 520,
                "km": 32000,
                "body_type": "suv",
            },
            {
                "url": "https://example.test/mazda-cx5-2023",
                "make": "Mazda",
                "model": "CX-5",
                "year": 2023,
                "price_usd": 24000,
                "monthly_est": 550,
                "km": 41000,
                "body_type": "suv",
            },
        ],
    )

    out = v14._advisor_brief(body)
    assert out is not None
    assert out["advisor_mode"] == "comparative_vehicle_brief_v14"
    assert out["llm_calls"] == 0
    reply = out["reply"].lower()
    assert "trade-off" in reply
    assert "antes de avanzar" in reply
    assert "familia de cinco" not in reply


def test_v51_is_outermost_vehicle_detail_route():
    route = next(r for r in v51.app.routes if getattr(r, "path", None) == "/carly/chat")
    assert getattr(route.endpoint, "_carly_v51_vehicle_detail", False) is True
