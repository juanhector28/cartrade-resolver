from app import main_v49 as v49


def _body(text):
    return {"messages": [{"role": "user", "content": text}], "country": "sv"}


def test_odometer_only_maximum_does_not_become_budget():
    c = v49._typed_constraints(_body("Es mi primer carro y no quiero pasar de 65,000 km."))
    assert c["max_km"] == 65000
    assert c.get("total_budget") is None


def test_budget_and_odometer_both_survive_with_correct_units():
    c = v49._typed_constraints(_body(
        "Quiero gastar máximo $11,000 y máximo 80,000 km. "
        "Preferiría Toyota, pero si otra marca me conviene claramente más, dímelo."
    ))
    assert c["total_budget"] == 11000
    assert c["max_km"] == 80000


def test_odometer_only_does_not_trigger_focused_retrieval():
    c = v49._typed_constraints(_body("Es mi primer carro y no quiero pasar de 65,000 km."))
    assert v49.v39._should_retrieve(c) is False


def test_price_and_mileage_hard_gates_are_independent():
    c = v49._typed_constraints(_body("Máximo $11,000 y máximo 80,000 km."))
    base = {
        "listing_state": "indexed",
        "is_addressable": True,
        "price_usd": 10500,
        "km": 79000,
        "make": "Toyota",
        "model": "Corolla",
        "year": 2020,
        "transmission": "Automática",
        "description": "",
    }
    assert v49.v48._hard_ok(dict(base), c)
    assert not v49.v48._hard_ok(dict(base, price_usd=11001), c)
    assert not v49.v48._hard_ok(dict(base, km=80001), c)


def test_missing_mileage_fails_closed_when_max_km_is_hard():
    c = v49._typed_constraints(_body("Máximo 80,000 km."))
    car = {
        "listing_state": "indexed",
        "is_addressable": True,
        "price_usd": 9000,
        "km": None,
        "make": "Honda",
        "model": "Fit",
        "year": 2019,
        "description": "",
    }
    assert not v49.v48._hard_ok(car, c)
