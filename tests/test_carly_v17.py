from app import main_v17 as v17


def _car(i):
    return {"id": str(i), "url": f"https://cars.test/{i}", "make": "Test", "model": f"Car {i}"}


def test_six_card_continuation_splits_into_featured_and_secondary():
    result = {
        "phase": "recommendation",
        "token_path": "deterministic_continuation",
        "recommendations": [_car(i) for i in range(1, 7)],
        "explore": [],
        "eligible_option_count": 10,
        "pool_size": 600,
    }
    out = v17._decorate_set(result)
    assert len(out["recommendations"]) == 3
    assert len(out["explore"]) == 3
    assert out["loaded_option_count"] == 6
    assert out["more_options_count"] == 4
    assert out["more_options_available"] is True
    assert "Encontré 6 opciones adicionales" in out["reply"]
    assert out["llm_calls"] == 0


def test_counts_use_eligible_set_not_market_pool():
    result = {
        "phase": "recommendation",
        "recommendations": [_car(1), _car(2)],
        "explore": [_car(3)],
        "market_pool_size": 600,
        "eligible_option_count": 3,
    }
    out = v17._decorate_set(result)
    assert out["market_pool_size"] == 600
    assert out["eligible_option_count"] == 3
    assert out["loaded_option_count"] == 3
    assert out["more_options_count"] == 0
    assert out["more_options_available"] is False


def test_single_source_loaded_options_contains_both_ui_buckets():
    result = {
        "phase": "recommendation",
        "recommendations": [_car(1), _car(2), _car(3)],
        "explore": [_car(4), _car(5), _car(6)],
        "eligible_option_count": 12,
        "market_pool_size": 600,
    }
    out = v17._decorate_set(result)
    assert len(out["loaded_options"]) == 6
    assert out["featured_option_count"] == 3
    assert out["secondary_option_count"] == 3
    assert out["remaining_option_count"] == 6
