from types import SimpleNamespace

from app import main_v18 as v18


def _car(i, make="Kia", model="Rio", body="sedan", year=2022, monthly=295):
    return {
        "id": str(i),
        "url": f"https://cars.test/{i}",
        "make": make,
        "model": model,
        "year": year,
        "km": 18000,
        "price_usd": 12000,
        "monthly_est": monthly,
        "body_type": body,
    }


def test_vehicle_brief_makes_cartrade_execution_owner(monkeypatch):
    focus = _car(1)
    pickup = _car(2, make="Mitsubishi", model="L 200", body="pickup", year=2025, monthly=450)
    body = SimpleNamespace(
        shown_cars=[focus, pickup],
        messages=[{"role":"user", "content":"Cuéntame más del Kia Rio 2022: ¿por qué me lo recomiendas y qué validarías antes de avanzar?"}],
    )
    profile = SimpleNamespace(primary_job="city_runabout", max_monthly=500, prefer_body=[], require_body=[])
    monkeypatch.setattr(v18, "_profile", lambda body, shown: profile)
    # Make the pickup score artificially huge. It still must not become the rival.
    monkeypatch.setattr(v18, "advisor_score", lambda car, profile: 999 if car["body_type"] == "pickup" else 10)
    result = v18._vehicle_brief(body)
    assert result["llm_calls"] == 0
    assert result["cartrade_execution_owner"] is True
    assert "Tú no tienes que encargarte" in result["reply"]
    assert "CarTrade" in result["reply"]
    assert "financiamiento" in result["reply"]
    assert "L 200" not in result["reply"]


def test_counts_never_use_market_pool_as_remaining():
    cards = [_car(i) for i in range(1, 4)]
    result = {
        "phase":"recommendation",
        "recommendations":cards,
        "explore":[],
        "market_pool_size":600,
        "eligible_option_count":9,
        "token_path":"deterministic_dynamic_preference",
    }
    out = v18._invariants(result)
    assert out["market_pool_size"] == 600
    assert out["eligible_option_count"] == 9
    assert out["loaded_option_count"] == 3
    assert out["remaining_option_count"] == 6
    assert out["more_options_count"] == 6
    assert out["more_options_batch_size"] == 6
    assert out["market_count_label"] == "vehículos analizados"
    assert "Encontré 3 opciones adicionales" in out["reply"]


def test_cta_batch_matches_actual_remaining():
    cards = [_car(i) for i in range(1, 7)]
    result = {
        "phase":"recommendation",
        "recommendations":cards[:3],
        "explore":cards[3:],
        "loaded_options":cards,
        "market_pool_size":347,
        "eligible_option_count":8,
    }
    out = v18._invariants(result)
    assert out["loaded_option_count"] == 6
    assert out["remaining_option_count"] == 2
    assert out["more_options_batch_size"] == 2
    assert out["more_options_cta"] == "Ver 2 más"


def test_no_more_cta_when_loaded_equals_eligible():
    cards = [_car(i) for i in range(1, 4)]
    out = v18._invariants({
        "phase":"recommendation",
        "recommendations":cards,
        "explore":[],
        "market_pool_size":600,
        "eligible_option_count":3,
    })
    assert out["more_options_available"] is False
    assert out["more_options_count"] == 0
    assert out["more_options_batch_size"] == 0
    assert out["more_options_cta"] is None
