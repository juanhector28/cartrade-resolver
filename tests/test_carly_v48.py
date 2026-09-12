from app import main_v48 as v48


def _body(text):
    return {"messages": [{"role": "user", "content": text}], "country": "sv"}


def _card(price=10000, km=60000, make="Toyota"):
    return {
        "make": make,
        "model": "Corolla",
        "year": 2022,
        "price_usd": price,
        "km": km,
        "body_type": "sedan",
        "transmission": "Automática",
        "listing_state": "indexed",
        "is_addressable": True,
        "url": f"https://example.test/{make}-{price}-{km}",
    }


def test_budget_and_odometer_are_typed_separately():
    c = v48._typed_constraints(_body(
        "Quiero gastar máximo $11,000 y máximo 80,000 km. "
        "Preferiría Toyota, pero si otra marca me conviene claramente más, dímelo."
    ))
    assert c["total_budget"] == 11000
    assert c["max_km"] == 80000
    assert "Toyota" in c.get("prefer_brands", [])
    assert not c.get("allowed_brands")


def test_hard_price_and_km_constraints_both_apply():
    c = v48._typed_constraints(_body(
        "Máximo $11,000 y máximo 80,000 km. Preferiría Toyota."
    ))
    assert v48._hard_ok(_card(price=10999, km=79999), c) is True
    assert v48._hard_ok(_card(price=11001, km=70000), c) is False
    assert v48._hard_ok(_card(price=10000, km=80001), c) is False


def test_missing_odometer_fails_closed_when_buyer_sets_max_km():
    c = v48._typed_constraints(_body("Máximo $11,000 y máximo 80,000 km."))
    card = _card()
    card["km"] = None
    assert v48._hard_ok(card, c) is False


def test_fast_profile_cannot_override_typed_budget():
    c = {"total_budget": 11000, "max_km": 80000, "typed_explicit_facts": {"max_price": 11000, "max_km": 80000}}
    fast = {"max_price": 80000}
    merged = v48._merge_fast_constraints(c, fast)
    assert merged["total_budget"] == 11000
    assert merged["max_km"] == 80000


def test_rebuild_publishes_canonical_constraints(monkeypatch):
    monkeypatch.setattr(v48, "_ORIG_REBUILD", lambda body, prior, c: {
        "profile": {},
        "recommendation_brain": {"hard_constraints": {}},
        "recommendations": [],
    })
    c = {"total_budget": 11000, "max_km": 80000, "daily_km": 20}
    result = v48._rebuild(_body("x"), {}, c)
    assert result["profile"]["max_price"] == 11000
    assert result["profile"]["max_km"] == 80000
    assert result["profile"]["daily_km"] == 20
    assert result["recommendation_brain"]["hard_constraints"]["max_km"] == 80000
    assert result["recommendation_brain"]["typed_constraint_authority"] is True
