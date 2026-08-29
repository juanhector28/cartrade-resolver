from types import SimpleNamespace

from app.carly_advisor import advisor_score, curate, rich_followup
from app.carly_quality_gate import eligible_for_profile, semantic_body


def city_profile():
    return SimpleNamespace(
        primary_job="city_runabout",
        prefer_body=["hatchback", "sedan"],
        require_body=[],
        max_monthly=500,
    )


def test_cmax_mislabeled_sedan_is_not_compact_city_candidate():
    car = {"make":"Ford","model":"C-Max Energi","body_type":"sedan","primary_photo":"x","price_usd":10500}
    assert semantic_body(car) == "mpv"
    assert eligible_for_profile(car, city_profile()) is False


def test_city_mission_prefers_true_city_hatch_over_older_generic_hatch():
    picanto = {"make":"Kia","model":"Picanto","year":2019,"km":74000,"body_type":"hatchback","monthly_est":167,"price_usd":7000,"primary_photo":"x"}
    fabia = {"make":"Skoda","model":"Fabia","year":2017,"km":45000,"body_type":"hatchback","monthly_est":119,"price_usd":5000,"primary_photo":"x"}
    assert advisor_score(picanto, city_profile()) > advisor_score(fabia, city_profile())


def test_curate_separates_endorsement_from_explore_and_caps_three():
    cars = [
        {"make":"Kia","model":"Picanto","year":2019,"km":74000,"body_type":"hatchback","monthly_est":167,"price_usd":7000,"primary_photo":"x","url":"1"},
        {"make":"Suzuki","model":"Alto","year":2023,"km":87000,"body_type":"hatchback","monthly_est":171,"price_usd":7200,"primary_photo":"x","url":"2"},
        {"make":"Mitsubishi","model":"Mirage","year":2023,"km":19000,"body_type":"hatchback","monthly_est":228,"price_usd":9600,"primary_photo":"x","url":"3"},
        {"make":"Honda","model":"Civic","year":2023,"km":133000,"body_type":"sedan","monthly_est":338,"price_usd":14200,"primary_photo":"x","url":"4"},
    ]
    strong, explore = curate(cars, city_profile())
    assert 1 <= len(strong) <= 3
    assert strong[0]["advisor_snapshot"]["label"] == "Mi favorita para tu caso"
    assert all(c["url"] not in {x["url"] for x in strong} for c in explore)


def test_rich_enquiry_takes_position_and_compares_without_llm():
    visible = [
        {"make":"Kia","model":"Picanto","year":2019,"km":74000,"body_type":"hatchback","monthly_est":167,"price_usd":7000,"url":"1"},
        {"make":"Skoda","model":"Fabia","year":2017,"km":45000,"body_type":"hatchback","monthly_est":119,"price_usd":5000,"url":"2"},
    ]
    reply = rich_followup("Cuéntame más del Skoda Fabia 2017: ¿por qué me lo recomiendas y qué debería preocuparme?", visible, city_profile())
    assert reply
    assert "Skoda Fabia 2017" in reply
    assert "Kia Picanto 2019" in reply
    assert "validaría" in reply
    assert len(reply.split()) >= 45
