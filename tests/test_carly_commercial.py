from app.carly_commercial import (
    commercialize_response,
    financing_for_car,
    financing_scenarios,
    has_monthly_signal,
    monthly_payment,
    preferred_budget_question,
    soften_advisory_tone,
)


def test_budget_question_is_low_friction_choice():
    text = "Perfecto. ¿Cuánto puedes destinar al mes en cuota, o tienes un precio total en mente?"
    out = preferred_budget_question(text)
    assert "¿Prefieres pensar en precio total o en una cuota mensual cómoda?" in out
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
