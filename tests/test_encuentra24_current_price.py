"""Regression tests for Encuentra24 live listing price selection."""
from app.resolvers.encuentra24 import extract_listing_headline_price


def test_discounted_jeep_uses_current_price_not_struck_out_original():
    body = (
        "Inicio Vehículos Autos Usados Jeep Gladiator "
        "Jeep Gladiator 2023 $ 43,182 $ 38,000 -12% "
        "Año 2023 Kilometraje 27,000 Combustible Gasolina "
        "Descripción Precio $45,000"
    )
    assert extract_listing_headline_price(body, "Jeep Gladiator 2023") == (38000, "USD")


def test_single_price():
    body = "Jeep Gladiator 2023 $ 38,000 Año 2023 Kilometraje 27,000"
    assert extract_listing_headline_price(body, "Jeep Gladiator 2023") == (38000, "USD")


def test_does_not_use_stale_description_or_related_car_price():
    body = "Jeep Gladiator 2023 Año 2023 Descripción Precio $45,000 Más anuncios $50,000"
    assert extract_listing_headline_price(body, "Jeep Gladiator 2023") == (None, None)


def test_different_currency():
    body = "Toyota Hilux 2022 Q 180,000 Q 165,000 Año 2022"
    assert extract_listing_headline_price(body, "Toyota Hilux 2022") == (165000, "GTQ")
