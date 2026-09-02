from app import main_v35 as v35


def test_mixed_budget_question_classifies_large_standalone_as_total():
    messages = [
        {"role": "user", "content": "Somos 5, incluyendo un bebé. Busco algo cómodo para ciudad."},
        {"role": "assistant", "content": "¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."},
        {"role": "user", "content": "18,000"},
    ]
    assert v35._max_price_from_messages(messages) == 18000


def test_exact_demo_conversation_retains_five_passengers():
    messages = [
        {
            "role": "user",
            "content": (
                "Vivo en San Salvador. Somos 5, incluyendo un bebé con silla infantil y coche. "
                "Busco algo cómodo para usar todos los días en ciudad, pero unas dos veces al mes manejo a Guatemala. "
                "No quiero pickup. Preferiría Toyota u Honda por confiabilidad. Automática sí o sí."
            ),
        },
        {"role": "assistant", "content": "¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."},
        {"role": "user", "content": "18,000"},
    ]
    profile = v35._extract_fast_profile(messages, country="sv")
    assert profile is not None
    assert profile["max_price"] == 18000
    assert profile["passengers"] == 5
    assert profile["small_children"] is True
    assert profile["primary_job"] == "family_transport"


def test_passenger_words_survive_punctuation():
    messages = [
        {"role": "user", "content": "Somos cinco, con equipaje y un bebé. Para la familia, máximo $18k."}
    ]
    profile = v35._extract_fast_profile(messages, country="sv")
    assert profile is not None
    assert profile["passengers"] == 5


def test_small_standalone_after_mixed_budget_question_stays_monthly():
    messages = [
        {"role": "user", "content": "Busco algo para la familia"},
        {"role": "assistant", "content": "¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."},
        {"role": "user", "content": "500"},
    ]
    assert v35._max_price_from_messages(messages) is None
    profile = v35._extract_fast_profile(messages, country="sv")
    assert profile is not None
    assert profile["max_monthly"] == 500
