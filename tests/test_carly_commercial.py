from app.carly_commercial import (
    commercialize_response,
    financing_for_car,
    preferred_budget_question,
    soften_advisory_tone,
)


def test_budget_question_is_low_friction_choice():
    text = "Perfecto. ¿Cuánto puedes destinar al mes en cuota, o tienes un precio total en mente?"
    out = preferred_budget_question(text)
    assert "¿Prefieres pensar en precio total o en una cuota mensual cómoda?" in out
    assert "Cuánto puedes destinar" not in out


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


def test_recommendation_gets_financing_metadata():
    result = {
        "phase": "recommendation",
        "reply": "Estas son mis mejores opciones.",
        "recommendations": [{"make": "Toyota", "model": "Yaris", "monthly_est": 300}],
        "decision": {"recommendations": [{"make": "Toyota", "model": "Yaris", "monthly_est": 300}]},
    }
    out = commercialize_response(result)
    assert out["financing"]["available"] is True
    assert out["financing"]["optional"] is True
    assert out["recommendations"][0]["financing"]["cta"] == "Ver financiamiento"
    assert out["decision"]["recommendations"][0]["financing"]["monthly_est"] == 300
