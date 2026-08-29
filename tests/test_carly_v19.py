from types import SimpleNamespace

from app import main_v19 as v19


def _car(i):
    return {
        "id": f"car-{i}",
        "url": f"https://example.com/{i}",
        "make": "Kia",
        "model": f"Model {i}",
        "year": 2020 + (i % 5),
        "km": 10000 + i * 1000,
        "price_usd": 9000 + i * 500,
        "monthly_est": 180 + i * 10,
        "body_type": "hatchback",
        "primary_photo": "https://example.com/photo.jpg",
    }


def test_initial_response_fills_six_and_keeps_truthful_remaining(monkeypatch):
    cars = [_car(i) for i in range(10)]
    profile = SimpleNamespace()
    body = SimpleNamespace(country="SV")
    monkeypatch.setattr(v19.v18, "_profile", lambda _body, _shown: profile)
    monkeypatch.setattr(v19.commercial.legacy, "_carly_inventory", lambda _profile, country=None: cars)
    monkeypatch.setattr(v19, "filter_pool", lambda rows, _profile: list(rows))
    monkeypatch.setattr(v19, "advisor_score", lambda car, _profile: float(car["year"]))
    monkeypatch.setattr(v19.v18.v17.v16, "_card", lambda row, _profile, _rank: dict(row))

    result = {
        "phase": "recommendation",
        "recommendations": [cars[0], cars[1]],
        "explore": [],
        "loaded_options": [cars[0], cars[1]],
        "market_pool_size": 600,
        "eligible_option_count": 2,
        "token_path": "deterministic_initial",
    }
    out = v19._expand_initial(body, result)
    assert len(out["loaded_options"]) == 6
    assert len(out["recommendations"]) == 3
    assert len(out["explore"]) == 3
    assert out["eligible_option_count"] == 10
    assert out["remaining_option_count"] == 4
    assert out["more_options_batch_size"] == 4
    assert out["more_options_cta"] == "Ver 4 más"
    assert out["market_pool_size"] == 600
