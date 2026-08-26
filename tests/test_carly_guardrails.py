from types import SimpleNamespace
import copy

from app.carly_guardrails import (
    apply_explicit_facts,
    extract_explicit_facts,
    passes_pinned_constraints,
    pin_hard_constraints,
)


def _profile():
    return SimpleNamespace(
        max_price=12000,
        max_monthly=None,
        min_year=None,
        require_body=[],
        exclude_body=[],
        require_brands=[],
        exclude_brands=[],
        exclude_transmission=None,
    )


def test_real_first_car_conversation_preserves_numeric_facts():
    messages = [
        {"role": "user", "content": "Mi primer carro. Abajo de 65,000 kms de uso."},
        {"role": "assistant", "content": "¿Para qué lo vas a usar principalmente?"},
        {"role": "user", "content": "Ir a la uni"},
        {"role": "assistant", "content": "¿Cuánto recorres al día?"},
        {"role": "user", "content": "mmm unos 20km diarios. No tengo un budget"},
        {
            "role": "assistant",
            "content": "¿Cuánto podrías destinar como máximo, ya sea al contado o en cuota mensual?",
        },
        {"role": "user", "content": "12k"},
    ]

    assert extract_explicit_facts(messages) == {
        "max_km": 65000,
        "daily_km": 20.0,
        "max_price": 12000.0,
    }


def test_hard_odometer_ceiling_rejects_every_overage_and_unknown_km():
    p = pin_hard_constraints(_profile(), {"max_km": 65000})

    assert passes_pinned_constraints(
        {"km": 65000, "price_usd": 12000, "body_type": "hatch", "make": "Suzuki"}, p
    )
    assert not passes_pinned_constraints(
        {"km": 65001, "price_usd": 10000, "body_type": "hatch", "make": "Honda"}, p
    )
    assert not passes_pinned_constraints(
        {"km": None, "price_usd": 10000, "body_type": "hatch", "make": "Honda"}, p
    )


def test_silent_budget_relaxation_cannot_override_pinned_ceiling():
    p = pin_hard_constraints(_profile(), {"max_km": 65000})
    relaxed = copy.deepcopy(p)
    relaxed.max_price = 50000

    assert not passes_pinned_constraints(
        {"km": 40000, "price_usd": 12001, "body_type": "hatch", "make": "Kia"},
        relaxed,
    )


def test_explicit_facts_mutate_returned_profile_payload():
    data = {"daily_km": 100, "max_price": None}
    apply_explicit_facts(data, {"daily_km": 20, "max_km": 65000, "max_price": 12000})

    assert data["daily_km"] == 20
    assert data["max_km"] == 65000
    assert data["max_price"] == 12000


def test_frontend_radius_context_does_not_become_daily_km():
    messages = [
        {
            "role": "user",
            "content": (
                "Voy 20 km diarios a la uni\n"
                "[CONTEXTO ACTIVO DE CARTRADE: San Salvador, El Salvador · 100 km; "
                "MODO CARLY: viejo]"
            ),
        }
    ]

    facts = extract_explicit_facts(messages)
    assert facts["daily_km"] == 20
    assert facts.get("max_km") is None
