from app.carly_state import (
    has_unresolved_decision_reset,
    is_profile_reset_text,
    latest_user_resets_decision,
)


def test_explicit_change_of_mission_starts_new_decision_epoch():
    messages = [
        {"role": "assistant", "content": "Estoy optimizando para: ciudad y bajo consumo."},
        {"role": "user", "content": "Busco un auto cómodo, seguro y eficiente para viajes largos"},
        {"role": "assistant", "content": "¿Estás cambiando lo que buscas o es un segundo carro?"},
        {"role": "user", "content": "Cambiando lo que busco"},
    ]
    assert latest_user_resets_decision(messages)
    assert has_unresolved_decision_reset(messages)


def test_old_shortlist_stays_stale_while_new_profile_is_being_built():
    messages = [
        {"role": "assistant", "content": "Estoy optimizando para: ciudad y bajo consumo."},
        {"role": "user", "content": "Cambiando lo que busco"},
        {"role": "assistant", "content": "Entendido. ¿Cuál es tu presupuesto?"},
        {"role": "user", "content": "el mismo de antes"},
        {"role": "assistant", "content": "¿Qué tan frecuentes son esos viajes largos?"},
        {"role": "user", "content": "3-4 veces al mes"},
        {"role": "assistant", "content": "¿Carretera pavimentada o terreno en mal estado?"},
        {"role": "user", "content": "hay tramos malos"},
    ]
    assert has_unresolved_decision_reset(messages)


def test_fresh_ranked_shortlist_resolves_decision_reset():
    messages = [
        {"role": "user", "content": "Cambiando lo que busco"},
        {"role": "assistant", "content": "Entendido. ¿Cuál es tu presupuesto?"},
        {"role": "user", "content": "$500 al mes"},
        {
            "role": "assistant",
            "content": "Estoy optimizando para: viajes largos, cuatro personas y terreno mixto. De todo lo que crucé, yo empezaría por la L200.",
        },
    ]
    assert not has_unresolved_decision_reset(messages)


def test_reset_language_variants_are_recognized():
    for text in (
        "Quiero cambiar lo que busco",
        "Empecemos de cero",
        "Quiero algo diferente",
        "Es un segundo carro",
    ):
        assert is_profile_reset_text(text), text
