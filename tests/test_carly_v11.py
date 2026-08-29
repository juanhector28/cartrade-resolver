from types import SimpleNamespace

from app import main_v11


def city_profile(max_monthly=500):
    return SimpleNamespace(
        primary_job="city_runabout",
        prefer_body=["hatchback", "sedan"],
        require_body=[],
        max_monthly=max_monthly,
    )


def test_fresh_intake_explicitly_clears_any_preloaded_panel():
    body = SimpleNamespace(
        country="SV",
        messages=[{"role":"user","content":"Busco un compacto para ciudad, económico y fácil de estacionar"}],
        shown_cars=[{"make":"Kia","model":"Picanto","year":2019}],
    )
    out = main_v11._fresh_intake_response(body)
    assert out is not None
    assert out["phase"] == "conversation"
    assert out["reply"] == "Entendido. ¿Qué cuota mensual te queda cómoda?"
    assert out["clear_recommendations"] is True
    assert out["replace_recommendations"] is True
    assert out["recommendations"] == []
    assert out["explore"] == []
    assert out["ui_state"] == "fresh_intake_empty"
    assert out["llm_calls"] == 0


def test_completed_budget_does_not_get_cleared_back_to_intake():
    body = SimpleNamespace(
        country="SV",
        messages=[
            {"role":"user","content":"Busco un compacto para ciudad, económico y fácil de estacionar"},
            {"role":"assistant","content":"Entendido. ¿Qué cuota mensual te queda cómoda?"},
            {"role":"user","content":"500"},
        ],
        shown_cars=None,
    )
    assert main_v11._fresh_intake_response(body) is None


def test_vehicle_brief_recovers_when_frontend_drops_prior_intake_history():
    visible = [
        {"make":"Mitsubishi","model":"Mirage","year":2024,"km":16000,"body_type":"hatchback","monthly_est":231,"price_usd":9700,"primary_photo":"x","url":"1","advisor_score":94,"advisor_snapshot":{"semantic_class":"city_hatch"}},
        {"make":"Kia","model":"Picanto","year":2019,"km":74000,"body_type":"hatchback","monthly_est":167,"price_usd":7000,"primary_photo":"x","url":"2","advisor_score":82,"advisor_snapshot":{"semantic_class":"city_hatch"}},
    ]
    body = SimpleNamespace(
        country="SV",
        messages=[{"role":"user","content":"Háblame del Kia Picanto 2019: pros y contras"}],
        shown_cars=visible,
    )
    out = main_v11._hierarchical_brief(body)
    assert out is not None
    assert out["llm_calls"] == 0
    assert out["token_path"] == "deterministic_vehicle_brief"
    assert "MI LECTURA ·" in out["reply"]
    assert "POR QUÉ ME GUSTA ·" in out["reply"]
    assert "OJO CON ·" in out["reply"]
    assert "CARTRADE LO VERIFICA ·" in out["reply"]
    assert "documentación de propiedad/registro" in out["reply"]
    assert "no como confirmado" in out["reply"]


def test_relative_explore_floor_drops_weak_tail(monkeypatch):
    monkeypatch.setattr(main_v11.v10, "_profile_from_result", lambda result: city_profile())
    cards = [
        {"make":"Mitsubishi","model":"Mirage","year":2024,"km":16000,"body_type":"hatchback","monthly_est":231,"price_usd":9700,"primary_photo":"x","url":"1","quality_score":85},
        {"make":"Suzuki","model":"Alto","year":2023,"km":30000,"body_type":"hatchback","monthly_est":171,"price_usd":7200,"primary_photo":"x","url":"2","quality_score":80},
        {"make":"Kia","model":"Picanto","year":2021,"km":45000,"body_type":"hatchback","monthly_est":190,"price_usd":8000,"primary_photo":"x","url":"3","quality_score":78},
        {"make":"Kia","model":"Forte","year":2011,"km":190000,"body_type":"sedan","monthly_est":480,"price_usd":19000,"primary_photo":"x","url":"4","quality_score":60},
    ]
    result = {"phase":"recommendation", "profile":{}, "recommendations":cards[:3], "explore":cards[3:]}
    out = main_v11._tighten_result(result)
    assert len(out["recommendations"]) <= 3
    assert len(out["explore"]) <= 4
    assert all(c.get("model") != "Forte" for c in out["explore"])
    assert out["advisor_policy"]["stable_over_novel"] is True


def test_v11_runtime_policy():
    assert main_v11.commercial.RUNTIME_COMPOSITION == "commercial-v11-state-brief-routing"
    assert main_v11.MAX_STRONG == 3
    assert main_v11.MAX_EXPLORE == 4
