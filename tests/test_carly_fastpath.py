from app.carly_fastpath import (
    deterministic_intake_reply,
    extract_fast_profile,
    intake_state,
)


def test_city_compact_monthly_is_zero_token_ready():
    messages = [
        {"role": "user", "content": "Necesito un auto compacto para ciudad, económico y fácil de estacionar. Máximo $500 al mes."}
    ]
    profile = extract_fast_profile(messages, country="sv")
    assert profile is not None
    assert profile["country"] == "sv"
    assert profile["primary_job"] == "city_runabout"
    assert profile["max_monthly"] == 500
    assert profile["priority"] == "economia"
    assert profile["cost_sensitivity"] == "high"
    assert profile["prefer_body"] == ["hatchback", "sedan"]


def test_standalone_monthly_answer_reuses_assistant_context():
    messages = [
        {"role": "user", "content": "Quiero algo compacto para ciudad"},
        {"role": "assistant", "content": "¿Qué cuota mensual te queda cómoda?"},
        {"role": "user", "content": "500"},
    ]
    profile = extract_fast_profile(messages, country="sv")
    assert profile is not None
    assert profile["max_monthly"] == 500
    assert profile["primary_job"] == "city_runabout"


def test_specific_model_falls_back_to_richer_path():
    messages = [
        {"role": "user", "content": "Quiero un Toyota Corolla para ciudad, máximo $500 al mes"}
    ]
    assert extract_fast_profile(messages, country="sv") is None


def test_unqualified_brand_mention_falls_back():
    messages = [
        {"role": "user", "content": "Toyota para ciudad, máximo $500 al mes"}
    ]
    assert extract_fast_profile(messages, country="sv") is None


def test_hard_brand_can_use_fastpath():
    messages = [
        {"role": "user", "content": "Solo Toyota para la familia, máximo $18k"}
    ]
    profile = extract_fast_profile(messages, country="sv")
    assert profile is not None
    assert profile["require_brands"] == ["Toyota"]
    assert profile["max_price"] == 18000
    assert profile["primary_job"] == "family_transport"


def test_work_pickup_keeps_body_constraint():
    messages = [
        {"role": "user", "content": "Necesito una pickup para mi negocio y cargar herramientas, máximo $18k"}
    ]
    profile = extract_fast_profile(messages, country="sv")
    assert profile is not None
    assert profile["primary_job"] == "work_vehicle"
    assert profile["require_body"] == ["pickup"]
    assert profile["max_price"] == 18000


def test_intent_without_budget_gets_deterministic_blocker():
    messages = [{"role": "user", "content": "Busco algo compacto para ciudad"}]
    assert deterministic_intake_reply(messages, country="sv") == "Entendido. ¿Qué cuota mensual te queda cómoda?"


def test_budget_without_intent_gets_use_question():
    messages = [{"role": "user", "content": "Máximo $15,000"}]
    assert deterministic_intake_reply(messages, country="sv") == "Perfecto. ¿Para qué usarías el carro principalmente?"


def test_monthly_is_not_misread_as_total_price():
    messages = [{"role": "user", "content": "Para ciudad, máximo $500 al mes"}]
    state = intake_state(messages, country="sv")
    assert state["max_monthly"] == 500
    assert state["max_price"] is None


def test_outer_fastpath_keeps_budget_question_concise():
    from types import SimpleNamespace
    from app.main_commercial import _deterministic_outer_fastpath

    body = SimpleNamespace(country="sv", shown_cars=[])
    messages = [{"role": "user", "content": "Busco un compacto para ciudad, económico y fácil de estacionar"}]
    out = _deterministic_outer_fastpath(body, messages)

    assert out is not None
    assert out["phase"] == "conversation"
    assert out["token_path"] == "deterministic"
    assert out["reply"] == "Entendido. ¿Qué cuota mensual te queda cómoda?"
    assert "precio total" not in out["reply"].lower()
