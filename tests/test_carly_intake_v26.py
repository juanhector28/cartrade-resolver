from types import SimpleNamespace

from app import main_v26 as v26


def _u(text):
    return {"role": "user", "content": text}


def _a(text):
    return {"role": "assistant", "content": text}


def test_work_pickup_language_is_normalized_without_llm():
    cases = [
        "Necesito una pickup potente y confiable para trabajar",
        "llevar ripio de sitios de construcción",
        "ripio",
        "cargas pesadas",
        "para transportar materiales",
    ]
    for text in cases:
        rows = v26._augment_intake([_u(text)])
        assert "vehiculo de trabajo" in rows[0]["content"]


def test_ambiguous_budget_range_after_budget_question_is_monthly():
    messages = [
        _u("Necesito una pickup potente y confiable para trabajar"),
        _a("¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."),
        _u("450-600"),
    ]
    assert v26._monthly_range(messages) == (450.0, 600.0)
    rows = v26._augment_intake(messages)
    assert "cuota maxima 600 al mes" in rows[-1]["content"]


def test_monthly_range_sets_target_and_ceiling_on_profile():
    messages = [
        _u("Necesito una pickup potente y confiable para trabajar"),
        _a("¿Qué tipo de carga o trabajo haces con ella normalmente?"),
        _u("llevar ripio de sitios de construcción"),
        _a("¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."),
        _u("450-600"),
    ]
    profile = v26._v26_extract_fast_profile(messages, country="sv")
    assert profile is not None
    assert profile["primary_job"] == "work_vehicle"
    assert profile["target_monthly"] == 450.0
    assert profile["max_monthly"] == 600.0
    assert "pickup" in profile["require_body"]


def test_exact_live_loop_no_longer_returns_usage_question():
    messages = [
        _u("Necesito una pickup potente y confiable para trabajar"),
        _a("¿Qué tipo de carga o trabajo haces con ella normalmente?"),
        _u("llevar ripio de sitios de construcción"),
        _a("¿Cuál es tu presupuesto? Puedes decirme precio total o cuota máxima."),
        _u("450-600"),
    ]
    reply = v26._v26_deterministic_reply(messages, country="sv")
    assert reply != "Perfecto. ¿Para qué usarías el carro principalmente?"


def test_student_university_journey_becomes_economic_daily_commute():
    messages = [
        _u("Carro para ir a la universidad. Algo económico"),
        _a("¿Cuántos kilómetros haces normalmente en un día de ida y vuelta a la uni?"),
        _u("15-20 kms"),
        _a("¿Cuánto puedes gastar en el carro; tienes un techo en mente?"),
        _u("Unos 15k"),
    ]
    profile = v26._v26_extract_fast_profile(messages, country="sv")
    assert profile is not None
    assert profile["primary_job"] == "daily_commute"
    assert profile["usage"] == "ciudad"
    assert profile["priority"] == "economia"
    assert profile["max_price"] == 15000.0
    assert profile["daily_km"] == 17.5


def test_student_economy_ranking_prefers_reliable_city_cars_over_old_cheapest_or_pickup():
    profile = SimpleNamespace(
        primary_job="daily_commute",
        priority="economia",
        max_price=15000,
        max_monthly=None,
    )
    yaris = {"make": "Toyota", "model": "Yaris", "year": 2021, "km": 52000, "price_usd": 13900, "body_type": "sedan"}
    picanto = {"make": "Kia", "model": "Picanto", "year": 2022, "km": 41000, "price_usd": 11900, "body_type": "hatchback"}
    eon = {"make": "Hyundai", "model": "EON", "year": 2018, "km": 117000, "price_usd": 6500, "body_type": "hatchback"}
    frontier = {"make": "Nissan", "model": "Frontier", "year": 2022, "km": 50000, "price_usd": 14500, "body_type": "pickup"}
    over_budget = {"make": "Honda", "model": "Civic", "year": 2023, "km": 20000, "price_usd": 19000, "body_type": "sedan"}

    ranked = sorted([eon, frontier, picanto, yaris, over_budget], key=lambda c: v26._mission_score(c, profile), reverse=True)
    assert ranked[0] in (yaris, picanto)
    assert ranked.index(eon) > ranked.index(yaris)
    assert ranked.index(frontier) > ranked.index(picanto)
    assert ranked[-1] == over_budget
