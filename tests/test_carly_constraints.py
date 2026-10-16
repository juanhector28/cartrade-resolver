from app.carly_constraints import parse, eligible

def test_open_request_has_no_fake_model():
    for text in (
        "Quiero un SUV familiar. Muéstrame las mejores opciones hasta $22,000",
        "Quiero mi primer carro. ¿Qué me recomiendas?",
        "Puedo dar $4,000 de prima y pagar $350 mensuales por un SUV",
    ):
        assert parse(text)["models"] == []

def test_compare_preserves_both_models():
    models = parse("Toyota RAV4 o Honda CR-V 2020 en adelante hasta $25,000")["models"]
    assert ("toyota", "rav4") in models
    assert ("honda", "cr-v") in models
    assert not eligible({"make": "Toyota", "model": "Tacoma"}, {"models": models,
        "body": None, "year_min": None, "km_max": None, "price_max": None,
        "monthly_max": None, "fuel": None, "drive": None})

def test_hard_filters_fail_closed():
    request = parse("pickup 4x4 diésel 2021 en adelante menos de 80,000 km presupuesto máximo de $28,000")
    car = {"make": "Honda", "model": "Ridgeline", "body_type": "pickup",
           "year": 2022, "km": 68498, "price_usd": 27271,
           "fuel_type": "Gasolina", "drivetrain": "4x4"}
    assert not eligible(car, request)
    car["fuel_type"] = "Diesel"
    car["drivetrain"] = None
    assert not eligible(car, request)
    car["drivetrain"] = "4x4"
    assert eligible(car, request)

def test_financing_limits_not_vehicle_price():
    filters = parse("Puedo dar $4,000 de prima y pagar $350 mensuales por un SUV usado")
    assert filters["down_payment"] == 4000
    assert filters["monthly_max"] == 350
    assert filters["price_max"] is None
