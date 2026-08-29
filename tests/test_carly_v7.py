from app import main_v7


def test_stale_cards_do_not_block_fresh_city_intake():
    messages = [
        {"role": "user", "content": "Busco un compacto para ciudad, económico y fácil de estacionar"},
    ]
    assert main_v7._is_high_confidence_intake_turn(messages, country="sv") is True


def test_stale_cards_do_not_block_standalone_monthly_answer():
    messages = [
        {"role": "user", "content": "Busco un compacto para ciudad, económico y fácil de estacionar"},
        {"role": "assistant", "content": "Entendido. ¿Qué cuota mensual te queda cómoda?"},
        {"role": "user", "content": "500"},
    ]
    assert main_v7._is_high_confidence_intake_turn(messages, country="sv") is True


def test_stale_cards_repair_when_assistant_turn_is_missing():
    messages = [
        {"role": "user", "content": "Busco un compacto para ciudad, económico y fácil de estacionar"},
        {"role": "user", "content": "500"},
    ]
    assert main_v7._is_high_confidence_intake_turn(messages, country="sv") is True


def test_real_vehicle_followup_keeps_visible_cards():
    messages = [
        {"role": "user", "content": "Busco un compacto para ciudad, máximo $500 al mes"},
        {"role": "user", "content": "Cuéntame más del Kia Rio 2021"},
    ]
    assert main_v7._is_high_confidence_intake_turn(messages, country="sv") is False
