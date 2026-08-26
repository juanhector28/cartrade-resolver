"""Focused Carly quality smoke tests.

These tests are deliberately deterministic and do not call Anthropic or Supabase.
They protect the interpretation and ranking contract that the conversational
layer depends on. Live end-to-end probes should exercise /carly/chat separately.
"""

from app.main import parse_intent


def test_family_budget_is_understood():
    it = parse_intent("SUV para mi familia, automático, menos de $15k")
    assert "suv" in (it.body_types or [])
    assert it.transmission == "Automática"
    assert it.price_max == 15000
    assert it.use == "familia"


def test_work_pickup_is_understood():
    it = parse_intent("pickup para trabajo")
    assert "pickup" in (it.body_types or [])
    assert it.use == "trabajo"


def test_first_car_budget_is_understood():
    it = parse_intent("mi primer auto, algo económico menos de 10k")
    assert it.use == "primer"
    assert it.price_max == 10000


def test_make_constraint_is_understood():
    it = parse_intent("Toyota automático bajo $18,000")
    assert (it.make or "").lower() == "toyota"
    assert it.transmission == "Automática"
    assert it.price_max == 18000


def test_full_equipment_intent_prefers_newer():
    it = parse_intent("quiero lo más full que tengan")
    assert it.use == "full"
    assert it.newest_first is True
