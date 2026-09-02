import os

os.environ.setdefault("REQUIREMENTS_DB", "/tmp/carly_v31_requirements.db")
os.environ.setdefault("CACHE_DB", "/tmp/carly_v31_cache.db")

from app import main_v31 as v31


def body(text: str):
    return {"messages": [{"role": "user", "content": text}], "country": "sv"}


def test_exact_rav4_bypasses_generic_intake_even_with_typo():
    c = v31._constraints(body("Quiero una Toyta Rav4 para uso diario, máximo US$500 al mes."))
    assert c["exact"][:2] == ("Toyota", "RAV4")
    assert c["monthly_max"] == 500


def test_only_sedan_automatic_becomes_hard_constraints():
    c = v31._constraints(body("Quiero únicamente sedán automático para ciudad. Máximo US$400 al mes."))
    assert c["require_body"] == "sedan"
    assert c["require_transmission"] == "automatic"
    assert c["monthly_max"] == 400


def test_crv_year_floor_is_hard_constraint():
    c = v31._constraints(body("Busco un Honda CR-V 2024 o más nuevo. Máximo US$450 al mes."))
    assert c["exact"][:2] == ("Honda", "CR-V")
    assert c["min_year"] == 2024


def test_family_of_five_rejects_micro_and_pickup():
    c = v31._constraints(body("Somos familia de 5 con un bebé. Máximo US$550 al mes."))
    assert c["passengers"] == 5
    assert not v31._mission_ok({"make": "Kia", "model": "Picanto", "body_type": "hatchback"}, c)
    assert not v31._mission_ok({"make": "Ford", "model": "Ranger", "body_type": "pickup"}, c)


def test_farm_three_people_rejects_saveiro():
    c = v31._constraints(body("Finca, grava, 3 pasajeros y herramientas pesadas. Máximo US$500 al mes."))
    card = {"make": "Volkswagen", "model": "Saveiro", "body_type": "pickup"}
    assert not v31._mission_ok(card, c)


def test_delivery_rejects_pickup():
    c = v31._constraints(body("Carro para delivery todos los días. Máximo US$250 al mes."))
    assert not v31._mission_ok({"make": "Toyota", "model": "Hilux", "body_type": "pickup"}, c)


def test_extreme_recent_work_truck_price_is_not_recommendable():
    card = {"make": "Toyota", "model": "Hilux", "year": 2021, "price_usd": 7000, "body_type": "pickup", "url": "https://example.test/hilux"}
    assert not v31._quality_ok(card)
