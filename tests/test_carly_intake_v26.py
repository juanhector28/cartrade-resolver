from app import main_v26 as v26


def _u(text):
    return {"role": "user", "content": text}


def _a(text):
    return {"role": "assistant", "content": text}


def test_work_pickup_language_is_normalized_without_llm():
    cases = [
        "Necesito una pickup potente y confiable para trabajar",
        "llevar ripio de sitios de construcción",
        "ripio",
        "cargas pesadas",
        "para transportar materiales",
    ]
    for text in cases:
        rows = v26._augment_intake([_u(text)])
        assert "vehiculo de trabajo" in rows[0]["content"]


def test_ambiguous_budget_range_after_budget_question_is_monthly():
    messages = [
        _u("Necesito una pickup potente y confiable para trabajar"),
        _a("¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."),
        _u("450-600"),
    ]
    assert v26._monthly_range(messages) == (450.0, 600.0)
    rows = v26._augment_intake(messages)
    assert "cuota maxima 600 al mes" in rows[-1]["content"]


def test_monthly_range_sets_target_and_ceiling_on_profile():
    messages = [
        _u("Necesito una pickup potente y confiable para trabajar"),
        _a("¿Qué tipo de carga o trabajo haces con ella normalmente?"),
        _u("llevar ripio de sitios de construcción"),
        _a("¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."),
        _u("450-600"),
    ]
    profile = v26._v26_extract_fast_profile(messages, country="sv")
    assert profile is not None
    assert profile["primary_job"] == "work_vehicle"
    assert profile["target_monthly"] == 450.0
    assert profile["max_monthly"] == 600.0
    assert "pickup" in profile["require_body"]


def test_exact_live_loop_no_longer_returns_usage_question():
    messages = [
        _u("Necesito una pickup potente y confiable para trabajar"),
        _a("¿Qué tipo de carga o trabajo haces con ella normalmente?"),
        _u("llevar ripio de sitios de construcción"),
        _a("¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."),
        _u("450-600"),
    ]
    reply = v26._v26_deterministic_reply(messages, country="sv")
    assert reply != "Perfecto. ¿Para qué usarías el carro principalmente?"
