from types import SimpleNamespace

from app import main_v16 as v16


def _car(i, make="Toyota", model=None, body="sedan", monthly=250):
    return {
        "id": str(i),
        "url": f"https://cars.test/{i}",
        "make": make,
        "model": model or f"Model {i}",
        "year": 2022 + (i % 3),
        "km": 10000 + i * 1000,
        "price_usd": 9000 + i * 100,
        "monthly_est": monthly,
        "body_type": body,
    }


def _profile():
    return SimpleNamespace(
        primary_job="city_runabout",
        max_monthly=300,
        prefer_body=["hatchback"],
        require_body=[],
        avoid_brands=[],
    )


def test_budget_margin_updates_monthly_zero_token(monkeypatch):
    shown = [_car(1, make="Honda", model="Civic", monthly=255)]
    body = SimpleNamespace(
        shown_cars=shown,
        country="sv",
        messages=[{"role":"user", "content":"por 500 dólares hay margen"}],
    )
    pool = shown + [_car(i, monthly=300 + i) for i in range(2, 9)]
    monkeypatch.setattr(v16.v15, "_profile", lambda body, visible: _profile())
    monkeypatch.setattr(v16.v15, "_latest", lambda body: body.messages[-1]["content"])
    monkeypatch.setattr(v16.commercial.legacy, "_carly_inventory", lambda profile, country=None: pool)
    monkeypatch.setattr(v16.commercial.legacy, "_carly_card", lambda row: dict(row))

    result = v16._dynamic_search(body)
    assert result["llm_calls"] == 0
    assert result["profile_mutations"]["max_monthly"] == 500
    assert "~$500/mes" in result["reply"]


def test_sedan_more_requeries_and_returns_new_sedans(monkeypatch):
    shown = [
        _car(1, make="Chevrolet", model="Spark", body="hatchback"),
        _car(2, make="Kia", model="Picanto", body="hatchback"),
    ]
    body = SimpleNamespace(
        shown_cars=shown,
        country="sv",
        messages=[
            {"role":"user", "content":"Quizás veamos sedanes también"},
            {"role":"user", "content":"noo. Quiero sedanes, más opciones"},
        ],
    )
    sedans = [_car(i, body="sedan") for i in range(3, 12)]
    pool = shown + sedans
    monkeypatch.setattr(v16.v15, "_profile", lambda body, visible: _profile())
    monkeypatch.setattr(v16.v15, "_latest", lambda body: body.messages[-1]["content"])
    monkeypatch.setattr(v16.commercial.legacy, "_carly_inventory", lambda profile, country=None: pool)
    monkeypatch.setattr(v16.commercial.legacy, "_carly_card", lambda row: dict(row))

    result = v16._dynamic_search(body)
    assert result["phase"] == "recommendation"
    assert result["profile_mutations"]["body_type"] == "sedan"
    assert result["profile_mutations"]["body_hard"] is True
    assert len(result["recommendations"]) == 6
    assert all(c["body_type"] == "sedan" for c in result["recommendations"])
    assert not ({c["url"] for c in shown} & {c["url"] for c in result["recommendations"]})
    assert result["llm_calls"] == 0


def test_rejected_visible_honda_is_excluded(monkeypatch):
    civic = _car(1, make="Honda", model="Civic", body="sedan")
    shown = [civic, _car(2, make="Kia", model="Picanto", body="hatchback")]
    body = SimpleNamespace(
        shown_cars=shown,
        country="sv",
        messages=[
            {"role":"user", "content":"Quizás veamos sedanes también"},
            {"role":"user", "content":"No quiero ese Honda. Está chocado."},
            {"role":"user", "content":"Quiero sedanes, más opciones"},
        ],
    )
    pool = [civic] + [_car(i, body="sedan") for i in range(3, 11)]
    monkeypatch.setattr(v16.v15, "_profile", lambda body, visible: _profile())
    monkeypatch.setattr(v16.v15, "_latest", lambda body: body.messages[-1]["content"])
    monkeypatch.setattr(v16.commercial.legacy, "_carly_inventory", lambda profile, country=None: pool)
    monkeypatch.setattr(v16.commercial.legacy, "_carly_card", lambda row: dict(row))

    result = v16._dynamic_search(body)
    assert civic["url"] not in {c["url"] for c in result["recommendations"]}
    assert result["excluded_visible_count"] >= 1
    assert result["llm_calls"] == 0


def test_truthful_counts_do_not_turn_market_pool_into_more_options():
    result = {
        "phase":"recommendation",
        "pool_size":347,
        "recommendations":[_car(1), _car(2), _car(3)],
        "explore":[],
        "quality_candidate_count":3,
        "more_options_available":True,
        "more_options_count":344,
    }
    out = v16._truthful_counts(result)
    assert out["market_pool_size"] == 347
    assert out["eligible_option_count"] == 3
    assert out["loaded_option_count"] == 3
    assert out["more_options_available"] is False
    assert out["more_options_count"] == 0
