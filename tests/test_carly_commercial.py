from types import SimpleNamespace

from app.carly_commercial import (
    commercialize_response,
    financing_for_car,
    financing_scenarios,
    has_monthly_signal,
    monthly_payment,
    preferred_budget_question,
    soften_advisory_tone,
)
from app import main_commercial


def test_budget_question_is_single_mode_agnostic_question():
    text = "Perfecto. ¿Cuánto puedes destinar al mes en cuota, o tienes un precio total en mente?"
    out = preferred_budget_question(text)
    assert "¿Cuál es tu presupuesto?" in out
    assert "precio total o cuota máxima" in out
    assert "Prefieres pensar" not in out
    assert "Cuánto puedes destinar" not in out


def test_existing_monthly_budget_is_reused_not_reasked():
    messages = [{"role": "user", "content": "Puedo pagar $500 al mes"}]
    assert has_monthly_signal(messages)
    result = {
        "phase": "conversation",
        "reply": "Perfecto. ¿Prefieres pensar en precio total o en una cuota mensual cómoda?",
    }
    out = commercialize_response(result, messages=messages)
    assert "Prefieres pensar" not in out["reply"]


def test_advisory_tone_avoids_fear_language():
    out = soften_advisory_tone(
        "Te diré qué debería preocuparte, los riesgos principales y las red flags."
    ).lower()
    assert "preocuparte" not in out
    assert "riesgos" not in out
    assert "red flags" not in out
    assert "validaría antes de avanzar" in out
    assert "puntos principales por confirmar" in out
    assert "señales que revisaría" in out


def test_financing_is_optional_buying_power():
    f = financing_for_car({"monthly_est": 318})
    assert f["available"] is True
    assert f["estimate"] is True
    assert "$318/mes" in f["label"]
    assert f["cta"] == "Ver financiamiento"
    assert "pre-calificación" in f["disclaimer"]


def test_monthly_payment_and_scenarios_are_deterministic():
    pmt = monthly_payment(10000, 0.12, 60)
    assert 220 < pmt < 225
    rows = financing_scenarios(18000, 10000, apr=0.12, months=60)
    assert rows[0]["down_payment"] == 0
    assert rows[-1]["down_payment"] == 10000
    assert rows[-1]["monthly_payment"] < rows[0]["monthly_payment"]
    assert rows[-1]["cash_retained"] == 0


def test_recommendation_gets_financing_and_advisor_metadata():
    result = {
        "phase": "recommendation",
        "reply": "Estas son mis mejores opciones.",
        "recommendations": [
            {"id": "1", "url": "u1", "make": "Toyota", "model": "Yaris", "year": 2022, "monthly_est": 300, "price_usd": 14000},
            {"id": "2", "url": "u2", "make": "Suzuki", "model": "Swift", "year": 2021, "monthly_est": 270, "price_usd": 12500},
        ],
        "decision": {"recommendations": [{"make": "Toyota", "model": "Yaris", "monthly_est": 300}]},
    }
    out = commercialize_response(result)
    assert out["financing"]["available"] is True
    assert out["financing"]["optional"] is True
    assert out["recommendations"][0]["financing"]["cta"] == "Ver financiamiento"
    assert out["decision"]["recommendations"][0]["financing"]["monthly_est"] == 300
    assert out["advisor"]["top_pick"]["name"] == "Toyota Yaris 2022"
    assert out["recommendation_depth"]["choices"] == [3, 5, 10]
    assert out["recommendation_depth"]["default"] == 3
    assert out["recommendation_depth"]["never_fill_below_quality_threshold"] is True


def test_standalone_500_survives_missing_assistant_context():
    messages = [
        {"role": "user", "content": "Busco un compacto para ciudad, económico y fácil de estacionar"},
        # Reproduces the live client-state race: prior assistant turn is absent.
        {"role": "user", "content": "500"},
    ]
    repaired = main_commercial._repair_missing_monthly_context(messages, country="sv")
    profile = main_commercial.preview.extract_fast_profile(repaired, country="sv")
    assert profile is not None
    assert profile["max_monthly"] == 500
    assert profile["primary_job"] == "city_runabout"


def test_rank_cap_never_returns_six_equal_strong_recommendations():
    def original(cars, profile, *args, **kwargs):
        return kwargs.get("top_n")

    capped = main_commercial._install_rank_cap(original, cap=3)
    assert capped([], object(), top_n=6) == 3
    assert capped([], object(), top_n=2) == 2


def test_inventory_gate_blocks_misclassified_pickup_before_explore():
    rows = [
        {
            "make": "Mitsubishi", "model": "L200", "year": 2025,
            "body_type": "sedan", "primary_photo": "x", "quality_score": 90,
        },
        {
            "make": "Kia", "model": "Rio", "year": 2021,
            "body_type": "hatchback", "primary_photo": "y", "quality_score": 90,
        },
    ]
    profile = SimpleNamespace(primary_job="city_runabout", prefer_body=["hatchback", "sedan"], require_body=[])

    wrapped = main_commercial._install_inventory_quality(lambda profile, **kwargs: rows)
    out = wrapped(profile)
    assert [c["model"] for c in out] == ["Rio"]


def test_compound_why_and_concern_followup_answers_both_questions():
    decision = main_commercial.preview.room.state.decision
    car = {
        "make": "Skoda", "model": "Fabia", "year": 2017,
        "body_type": "hatchback", "price_usd": 5000, "monthly_est": 119,
    }
    reply = decision._deterministic_followup(
        "Cuéntame más del Skoda Fabia 2017: ¿por qué me lo recomiendas y qué debería preocuparme?",
        [car], [car], {},
    )
    low = reply.lower()
    assert "porque" in low
    assert "valid" in low
    assert "publicado en $5,000. ese es el precio" not in low
