from app import main_v20  # noqa: F401
from app.carly_fastpath import deterministic_intake_reply, extract_fast_profile, intake_state


def _finca_screenshot_journey():
    return [
        {"role": "user", "content": "Pickup 2020 o más nueva"},
        {"role": "assistant", "content": "Para darte el mejor shortlist, ¿cuál es tu techo de presupuesto?"},
        {"role": "user", "content": "550"},
        {"role": "assistant", "content": "¿$550 al mes en cuota, o $550,000 como precio total?"},
        {"role": "user", "content": "Cuota"},
        {"role": "assistant", "content": "¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."},
        {"role": "user", "content": "500"},
        {"role": "assistant", "content": "Perfecto. ¿Para qué usarías el carro principalmente?"},
        {"role": "user", "content": "para ir a mi finca"},
    ]


def _family_beach_journey():
    return [
        {"role": "user", "content": "Carro familiar. Para ir a la playa"},
        {"role": "assistant", "content": "¡Perfecto! Carro familiar para la playa sugiere espacio y carretera. ¿Cuántas personas viajan normalmente cuando van?"},
        {"role": "user", "content": "4-5"},
        {"role": "assistant", "content": "¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."},
        {"role": "user", "content": "cuota de 500 al mes"},
        {"role": "assistant", "content": "Perfecto. ¿Para qué usarías el carro principalmente?"},
        {"role": "user", "content": "ya te lo dije."},
        {"role": "assistant", "content": "Perfecto. ¿Para qué usarías el carro principalmente?"},
        {"role": "user", "content": "Para ir a la playa."},
    ]


def test_finca_answer_satisfies_primary_use_question():
    messages = _finca_screenshot_journey()
    state = intake_state(messages, country="sv")
    assert state["budget_known"] is True
    assert state["max_monthly"] == 500
    assert state["intent_known"] is True
    assert state["job"] == "work_vehicle"
    assert deterministic_intake_reply(messages, country="sv") is None


def test_finca_journey_can_build_deterministic_profile():
    profile = extract_fast_profile(_finca_screenshot_journey(), country="sv")
    assert profile is not None
    assert profile["max_monthly"] == 500
    assert profile["primary_job"] == "work_vehicle"
    assert profile["usage"] == "trabajo"


def test_family_beach_history_satisfies_primary_use_once_budget_is_known():
    messages = _family_beach_journey()
    state = intake_state(messages, country="sv")
    assert state["budget_known"] is True
    assert state["max_monthly"] == 500
    assert state["intent_known"] is True
    assert state["job"] == "family_transport"
    assert deterministic_intake_reply(messages, country="sv") is None


def test_family_beach_journey_builds_profile_without_reasking_use():
    profile = extract_fast_profile(_family_beach_journey(), country="sv")
    assert profile is not None
    assert profile["max_monthly"] == 500
    assert profile["primary_job"] == "family_transport"
    assert profile["usage"] == "familia"


def test_common_family_and_leisure_phrases_are_known_intent():
    for answer in ("carro familiar", "para mi familia", "para ir a la playa", "para vacaciones", "paseos familiares"):
        messages = [
            {"role": "user", "content": answer},
            {"role": "assistant", "content": "¿Cuál es tu presupuesto?"},
            {"role": "user", "content": "cuota de 500 al mes"},
        ]
        assert deterministic_intake_reply(messages, country="sv") is None


def test_rural_synonyms_do_not_repeat_use_question():
    for answer in ("voy al campo", "para una granja", "camino de tierra", "zona rural", "para mi terreno"):
        messages = [
            {"role": "user", "content": "Busco pickup"},
            {"role": "assistant", "content": "¿Qué cuota mensual te queda cómoda?"},
            {"role": "user", "content": "500"},
            {"role": "assistant", "content": "Perfecto. ¿Para qué usarías el carro principalmente?"},
            {"role": "user", "content": answer},
        ]
        assert deterministic_intake_reply(messages, country="sv") is None
