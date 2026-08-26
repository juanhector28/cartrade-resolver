from app.main_decision import _referenced_cars, _reply_violations


CARS = [
    {
        "make": "Toyota", "model": "Agya", "year": 2020,
        "price_usd": 8500, "km": 41000, "match_pct": 87.0,
    },
    {
        "make": "Mitsubishi", "model": "Mirage", "year": 2022,
        "price_usd": 9300, "km": 49000, "value_delta_pct": 6.3, "match_pct": 88.0,
    },
]


def test_named_vehicle_is_resolved_deterministically():
    refs = _referenced_cars("Cuéntame más del Toyota Agya 2020", CARS)
    assert len(refs) == 1
    assert refs[0]["model"] == "Agya"


def test_ungrounded_percentage_is_blocked_for_focused_vehicle():
    refs = _referenced_cars("Cuéntame más del Toyota Agya 2020", CARS)
    bad = "El Toyota Agya 2020 tiene 16% de match para ti."
    violations = _reply_violations(bad, "Cuéntame más del Toyota Agya 2020", refs, CARS)
    assert any("ungrounded percentage" in x for x in violations)


def test_grounded_percentage_is_allowed_for_focused_vehicle():
    refs = _referenced_cars("Cuéntame más del Toyota Agya 2020", CARS)
    good = "El Toyota Agya 2020 tiene 87% de match para ti y aún requiere verificación."
    assert _reply_violations(good, "Cuéntame más del Toyota Agya 2020", refs, CARS) == []


def test_exact_airbag_count_is_blocked_when_unit_data_does_not_have_it():
    refs = _referenced_cars("¿El Toyota Agya 2020 tiene exactamente 6 airbags?", CARS)
    bad = "El Toyota Agya 2020 tiene 6 airbags."
    violations = _reply_violations(bad, "¿El Toyota Agya 2020 tiene exactamente 6 airbags?", refs, CARS)
    assert any("airbag" in x for x in violations)


def test_unknown_airbag_answer_passes_when_explicitly_unverified():
    refs = _referenced_cars("¿El Toyota Agya 2020 tiene exactamente 6 airbags?", CARS)
    good = "Del Toyota Agya 2020 no tengo confirmado el número exacto de airbags; hay que verificarlo."
    assert _reply_violations(good, "¿El Toyota Agya 2020 tiene exactamente 6 airbags?", refs, CARS) == []


def test_carly_cannot_deny_a_visible_curated_car():
    refs = _referenced_cars("Cuéntame del Mitsubishi Mirage 2022", CARS)
    bad = "No te lo recomendé. El Mitsubishi Mirage 2022 no estaba entre mis opciones."
    violations = _reply_violations(bad, "Cuéntame del Mitsubishi Mirage 2022", refs, CARS)
    assert any("curated" in x for x in violations)
