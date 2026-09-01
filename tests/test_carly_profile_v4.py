from app.carly_profile import (
    MAX_QUESTIONS,
    extract_facts_regex,
    merge_facts,
    plan_turn,
)


def test_common_commute_message_captures_ceiling_without_llm():
    facts = extract_facts_regex(
        "Quiero algo económico para ir al trabajo, máximo $300 al mes."
    )
    assert facts["primary_job"] == "daily_commute"
    assert facts["max_monthly"] == 300
    assert facts["cost_sensitivity"] == "high"


def test_monthly_target_and_ceiling_are_kept_separately():
    facts = extract_facts_regex("Ideal 250, pero puedo llegar a 450 si vale la pena")
    assert facts["target_monthly"] == 250
    assert facts["max_monthly"] == 450


def test_latam_thousands_and_mil_suffix_are_total_budgets():
    assert extract_facts_regex("Presupuesto máximo 15.000")["max_price"] == 15000
    assert extract_facts_regex("Presupuesto de 10 mil")["max_price"] == 10000


def test_work_pickup_and_daily_range_are_structured():
    work = extract_facts_regex("Necesito una pickup para trabajar y llevar ripio")
    assert work["primary_job"] == "work_vehicle"
    assert work["require_body"] == ["pickup"]

    commute = extract_facts_regex("Hago 15-20 kms al día para ir al trabajo")
    assert commute["primary_job"] == "daily_commute"
    assert commute["daily_km"] == 17.5


def test_later_explicit_fact_replaces_stale_fact():
    facts = merge_facts({"max_monthly": 300}, {"max_monthly": 450})
    assert facts["max_monthly"] == 450


def test_question_budget_is_hard_and_deterministic():
    first = plan_turn(
        "Algo económico para ir al trabajo, máximo 300 al mes",
        known_facts={"country": "sv"},
        questions_asked=0,
    )
    assert first["decision"]["action"] == "ask"
    assert first["needs_llm"] is False

    second = plan_turn(
        "Hago 25 km diarios",
        known_facts=first["facts"],
        questions_asked=1,
    )
    assert second["decision"]["action"] == "recommend"
    assert second["needs_llm"] is False
    assert MAX_QUESTIONS == 2


def test_deterministic_blocker_question_never_needs_llm():
    plan = plan_turn(
        "Máximo 15 mil",
        known_facts={"country": "sv"},
        questions_asked=0,
    )
    assert plan["decision"]["action"] == "ask"
    assert plan["needs_llm"] is False

