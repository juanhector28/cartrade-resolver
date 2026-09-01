from app.carly_preview_first import assistant_question_turns, has_budget_signal, preview_policy


def m(role, content):
    return {"role": role, "content": content}


def test_down_payment_alone_is_not_affordability_ceiling():
    messages = [m("user", "Quiero un Prado, tengo aproximadamente $3,000 de prima.")]
    assert has_budget_signal(messages) is False
    policy = preview_policy(messages)
    assert policy["force_preview"] is False


def test_prado_case_previews_after_budget_answer():
    messages = [
        m("user", "Quiero un Prado, tengo aproximadamente $3,000 de prima."),
        m("assistant", "¿Hasta qué cuota mensual te sentirías cómodo?"),
        m("user", "$1,200 al mes máximo."),
    ]
    policy = preview_policy(messages)
    assert assistant_question_turns(messages) == 1
    assert policy["budget_signal"] is True
    assert policy["force_preview"] is True
    assert policy["reason"] == "enough_information_early"


def test_initial_vague_request_can_still_ask_a_useful_question():
    policy = preview_policy([m("user", "Estoy pensando comprar un carro.")])
    assert policy["questions"] == 0
    assert policy["force_preview"] is False
    assert policy["reason"] == "one_blocker_may_remain"


def test_two_questions_is_target_when_budget_and_use_are_known():
    messages = [
        m("user", "Estoy buscando un carro."),
        m("assistant", "¿Para qué lo vas a usar principalmente?"),
        m("user", "Para mi familia, somos cuatro."),
        m("assistant", "¿Cuál es tu presupuesto máximo?"),
        m("user", "$18,000 máximo."),
    ]
    policy = preview_policy(messages)
    assert policy["questions"] == 2
    assert policy["force_preview"] is True
    assert policy["reason"] == "hard_cap_two_questions"


def test_third_question_is_never_allowed_even_when_a_blocker_remains():
    messages = [
        m("user", "Estoy viendo opciones."),
        m("assistant", "¿Qué necesitas resolver con el carro?"),
        m("user", "Todavía no sé."),
        m("assistant", "¿Tienes una referencia de presupuesto?"),
        m("user", "No todavía."),
    ]
    policy = preview_policy(messages)
    assert policy["questions"] == 2
    assert policy["force_preview"] is True
    assert policy["reason"] == "hard_cap_two_questions"


def test_existing_three_question_history_is_forced_immediately():
    messages = [
        m("user", "Estoy viendo opciones."),
        m("assistant", "¿Uso?"), m("user", "No sé."),
        m("assistant", "¿Presupuesto?"), m("user", "No sé."),
        m("assistant", "¿Algún tipo de carro?"), m("user", "No sé."),
    ]
    policy = preview_policy(messages)
    assert policy["questions"] == 3
    assert policy["force_preview"] is True
    assert policy["reason"] == "hard_cap_two_questions"


def test_visible_market_disables_pre_preview_cap():
    messages = [
        m("user", "Quiero comparar estos."),
        m("assistant", "¿Qué te preocupa del primero?"),
        m("user", "El mantenimiento."),
        m("assistant", "¿Y del segundo?"),
        m("user", "El consumo."),
        m("assistant", "¿Quieres que tome posición?"),
        m("user", "Sí."),
    ]
    policy = preview_policy(messages, has_visible_cars=True)
    assert policy["force_preview"] is False
    assert policy["reason"] == "already_has_market"
