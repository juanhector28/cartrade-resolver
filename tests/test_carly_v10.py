from types import SimpleNamespace

from app.carly_vehicle_brief import build_vehicle_brief, model_guidance
from app import main_v10


def city_profile():
    return SimpleNamespace(primary_job="city_runabout", prefer_body=["hatchback", "sedan"], require_body=[], max_monthly=500)


def test_vehicle_brief_has_sections_and_zero_llm():
    visible = [
        {"make":"Mitsubishi","model":"Mirage","year":2024,"km":16000,"body_type":"hatchback","monthly_est":231,"price_usd":9700,"primary_photo":"x","url":"1"},
        {"make":"Suzuki","model":"Alto","year":2023,"km":87000,"body_type":"hatchback","monthly_est":171,"price_usd":7200,"primary_photo":"x","url":"2"},
    ]
    brief = build_vehicle_brief("Cuéntame más del Mitsubishi Mirage 2024: pros y contras", visible, city_profile(), country="SV")
    assert brief is not None
    assert brief["llm_calls"] == 0
    assert [x["title"] for x in brief["sections"]] == ["Mi lectura", "Por qué me gusta", "Ojo con", "CarTrade lo verifica"]
    assert "CARTRADE LO VERIFICA" in brief["reply"]
    assert "documentación de propiedad/registro" in brief["reply"]


def test_guidance_varies_by_model():
    assert model_guidance({"model":"Mirage"}) != model_guidance({"model":"Picanto"})


def test_v10_filters_incompatible_explore(monkeypatch):
    monkeypatch.setattr(main_v10, "_profile_from_result", lambda result: city_profile())
    cards = [
        {"make":"Mitsubishi","model":"Mirage","year":2024,"km":16000,"body_type":"hatchback","monthly_est":231,"price_usd":9700,"primary_photo":"x","url":"1"},
        {"make":"Suzuki","model":"Alto","year":2023,"km":87000,"body_type":"hatchback","monthly_est":171,"price_usd":7200,"primary_photo":"x","url":"2"},
        {"make":"Mitsubishi","model":"L200","year":2025,"km":27500,"body_type":"sedan","monthly_est":119,"price_usd":5000,"primary_photo":"x","url":"3"},
    ]
    result = {"phase":"recommendation", "profile":{}, "recommendations":cards[:2], "explore":cards[2:]}
    out = main_v10._tighten_recommendations(result)
    assert all(c.get("model") != "L200" for c in list(out["recommendations"]) + list(out["explore"]))
    assert len(out["recommendations"]) <= 3
    assert len(out["explore"]) <= 6


def test_v10_runtime_policy():
    assert main_v10.commercial.RUNTIME_COMPOSITION == "commercial-v10-verification-briefs"
    assert main_v10.MAX_STRONG == 3
    assert main_v10.MAX_EXPLORE == 6
