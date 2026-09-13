import os
from types import SimpleNamespace

os.environ.setdefault("CACHE_DB", "/tmp/carly-v56-cache.db")
os.environ.setdefault("TRUSTPLUS_DB", "/tmp/carly-v56-trustplus.db")
os.environ.setdefault("CARLY_VISION_JIT_ENABLED", "0")

from app import main_v51 as v51
from app import carly_v54_more_options as v54
from app import carly_v55_model_intelligence as v55
from app import carly_v56_buy_decision as v56


HIDDEN = (
    "[CONTEXTO ACTIVO DE CARTRADE: ubicación seleccionada por el usuario = Ciudad de Guatemala, Guatemala; "
    "MODO CARLY: precio, kilometraje, cuota y posibilidad de ver más opciones. "
    "FOLLOW-UP INTENT = UNIT_ASSESSMENT.]"
)


def _body(prompt="¿Es buena compra el Honda HR-V 2023?"):
    return SimpleNamespace(
        country="gt",
        messages=[
            {"role": "user", "content": "SUV familiar para llevar a mis hijos"},
            {"role": "assistant", "content": "¿Qué cuota mensual te queda cómoda?"},
            {"role": "user", "content": "650"},
            {"role": "assistant", "content": "El Honda HR-V 2023 es uno de tus finalistas."},
            {"role": "user", "content": prompt + "\n\n" + HIDDEN},
        ],
        shown_cars=[
            {
                "id": "hrv23",
                "url": "https://example.test/hrv23",
                "make": "Honda",
                "model": "HR-V",
                "year": 2023,
                "km": 19,
                "monthly_est": 402,
                "price_usd": 16900,
                "value_delta_pct": 1.5,
                "body_type": "suv",
            },
            {
                "id": "hrv22",
                "url": "https://example.test/hrv22",
                "make": "Honda",
                "model": "HR-V",
                "year": 2022,
                "km": 38000,
                "monthly_est": 362,
                "price_usd": 15200,
                "value_delta_pct": -1.0,
                "body_type": "suv",
            },
        ],
    )


def test_followup_golden_matrix_keeps_intents_separate():
    body = _body()
    assert v56._is_buy_decision(body) is True

    body.messages[-1]["content"] = "Dame los pros y cons del Honda HR-V 2023\n\n" + HIDDEN
    assert v56._is_buy_decision(body) is False
    assert v55._is_model_intelligence(body) is True

    body.messages[-1]["content"] = "Muéstrame más opciones con distintos trade-offs\n\n" + HIDDEN
    assert v56._is_buy_decision(body) is False
    assert v54._is_more_options(body) is True

    body.messages[-1]["content"] = "¿Cuál escogerías entre el HR-V 2023 y el HR-V 2022?\n\n" + HIDDEN
    assert v56._is_buy_decision(body) is False
    assert v55._is_model_intelligence(body) is False


def test_good_buy_answer_combines_unit_market_fit_and_verdict():
    out = v56.buy_decision(_body())
    assert out is not None
    assert out["route_precedence"] == "buy_decision_v56"
    assert out["buyer_decision"] is True
    assert out["llm_calls"] == 0
    reply = out["reply"].lower()
    assert "veredicto" in reply
    assert "por qué" in reply
    assert "lo que me frena" in reply
    assert "qué cambiaría mi opinión" in reply
    assert "mercado" in reply or "comparables" in reply
    assert "$248/mes" in reply
    assert "19 km" in reply
    assert "inusualmente bajos" in reply
    assert "antes de comprar" not in reply
    assert "puede encajar por precio y disponibilidad" not in reply
    assert "necesita más evidencia antes de saber" not in reply


def test_good_buy_does_not_reward_implausibly_low_reported_km():
    out = v56.buy_decision(_body())
    reply = out["reply"].lower()
    assert "no los usaría como ventaja hasta confirmar" in reply


def test_expensive_unit_gets_no_at_this_price_verdict():
    body = _body("¿Es buena compra el Honda HR-V 2023?")
    body.shown_cars[0]["value_delta_pct"] = 14.0
    out = v56.buy_decision(body)
    assert out is not None
    assert out["market_state"] == "high"
    assert "no a este precio" in out["reply"].lower()


def test_pronoun_good_buy_resolves_recently_discussed_vehicle():
    body = _body("¿Es buena compra esta unidad?")
    out = v56.buy_decision(body)
    assert out is not None
    assert out["focus"] == "Honda HR-V 2023"


def test_ambiguous_pronoun_does_not_guess_a_vehicle():
    body = _body("¿Es buena compra esta unidad?")
    body.messages[-2] = {"role": "assistant", "content": "Aquí tienes dos finalistas fuertes."}
    out = v56.buy_decision(body)
    assert out is not None
    assert "necesito saber cuál" in out["reply"].lower()


def test_v56_is_outermost_and_preserves_v55_v54_below_it():
    route = next(r for r in v51.app.routes if getattr(r, "path", None) == "/carly/chat")
    assert getattr(route.endpoint, "_carly_v56_buy_decision", False) is True
    v55_prior = getattr(route.endpoint, "_carly_v56_prior", None)
    assert getattr(v55_prior, "_carly_v55_model_intelligence", False) is True
    v54_prior = getattr(v55_prior, "_carly_v55_prior", None)
    assert getattr(v54_prior, "_carly_v54_more_options", False) is True
