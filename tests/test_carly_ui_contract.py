from app.carly_ui_contract import (
    apply_ui_contract,
    message_names_car,
    requested_year,
    should_show_market_animation,
)


def test_market_animation_only_when_new_shortlist_materializes():
    conversation = {"phase": "conversation", "reply": "Te cuento del Swift."}
    rebuilding = {
        "phase": "conversation",
        "decision_state": "rebuilding",
        "recommendations": [],
    }
    recommendation = {
        "phase": "recommendation",
        "recommendations": [{"make": "Suzuki", "model": "Swift", "year": 2021}],
    }

    assert not should_show_market_animation(conversation)
    assert not should_show_market_animation(rebuilding)
    assert should_show_market_animation(recommendation)

    out = apply_ui_contract(conversation)
    assert out["show_market_animation"] is False
    assert out["market_search_performed"] is False

    out = apply_ui_contract(recommendation)
    assert out["show_market_animation"] is True
    assert out["market_search_performed"] is True
    assert out["shown_cars_scope"] == "all_visible_cards"


def test_named_explore_card_is_recognized_from_model_and_year():
    car = {"make": "Nissan", "model": "Sentra", "year": 2022}
    assert message_names_car(
        "Cuéntame más del Nissan Sentra 2022: ¿qué debería preocuparme?", car
    )
    assert message_names_car("Háblame del Sentra 2022", car)
    assert not message_names_car("Háblame del Sentra 2021", car)
    assert requested_year("Háblame del Nissan Sentra 2022") == 2022
