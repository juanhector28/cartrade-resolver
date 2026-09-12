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
