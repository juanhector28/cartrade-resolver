from app import main_v20  # noqa: F401
from app.carly_buyer_state import build_buyer_state, next_blocker


def test_beach_family_answer_closes_primary_use_slot():
    messages = [
        {"role": "user", "content": "Carro familiar. Para ir a la playa"},
        {"role": "assistant", "content": "¿Cuántas personas viajan normalmente cuando van?"},
        {"role": "user", "content": "4-5"},
        {"role": "assistant", "content": "¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."},
        {"role": "user", "content": "cuota de 500 al mes"},
        {"role": "assistant", "content": "Perfecto. ¿Para qué usarías el carro principalmente?"},
        {"role": "user", "content": "Para ir a la playa."},
    ]
    state = build_buyer_state(messages, country="sv")
    assert state["primary_use_known"] is True
    assert state["primary_use_answer"] == "Para ir a la playa."
    assert state["budget_known"] is True
    assert state["max_monthly"] == 500
    assert state["passengers_known"] is True
    assert next_blocker(messages, country="sv") is None


def test_arbitrary_natural_language_answer_closes_asked_slot_without_synonym_rules():
    messages = [
        {"role": "assistant", "content": "Perfecto. ¿Para qué usarías el carro principalmente?"},
        {"role": "user", "content": "Los fines de semana llevo tablas, un perro enorme y a mis suegros fuera de la ciudad."},
        {"role": "assistant", "content": "¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."},
        {"role": "user", "content": "Máximo $20,000"},
    ]
    state = build_buyer_state(messages, country="sv")
    assert state["primary_use_known"] is True
    assert state["budget_known"] is True
    assert next_blocker(messages, country="sv") is None


def test_meta_answer_does_not_fake_slot_but_previous_real_answer_remains_closed():
    messages = [
        {"role": "assistant", "content": "¿Para qué usarías el carro principalmente?"},
        {"role": "user", "content": "Para viajes familiares a la costa"},
        {"role": "assistant", "content": "¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."},
        {"role": "user", "content": "cuota de 500 al mes"},
        {"role": "assistant", "content": "Perfecto. ¿Para qué usarías el carro principalmente?"},
        {"role": "user", "content": "ya te lo dije."},
    ]
    state = build_buyer_state(messages, country="sv")
    assert state["primary_use_known"] is True
    assert state["primary_use_answer"] == "Para viajes familiares a la costa"
    assert next_blocker(messages, country="sv") is None


def test_unknown_use_still_gets_one_blocker():
    messages = [
        {"role": "assistant", "content": "¿Cuál es tu presupuesto?"},
        {"role": "user", "content": "Máximo $18,000"},
    ]
    assert next_blocker(messages, country="sv") == "Perfecto. ¿Para qué usarías el carro principalmente?"
