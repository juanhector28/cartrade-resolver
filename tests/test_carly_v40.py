from app import main_v40 as v40


def _body(text):
    return {"messages": [{"role": "user", "content": text}], "country": "sv"}


def _card(make, model, body="suv", year=2024, price=15000, monthly=350, transmission="Automática", **extra):
    row = {
        "make": make, "model": model, "year": year, "price_usd": price,
        "monthly_est": monthly, "body_type": body, "transmission": transmission,
        "listing_state": "indexed", "is_addressable": True,
        "url": f"https://example.com/{make}-{model}",
    }
    row.update(extra)
    return row


def test_prompt1_forces_retrieval_and_keeps_negative_constraints():
    c = v40._constraints(_body(
        "Quiero algo cómodo para ciudad y carretera, automático, máximo US$425 al mes. "
        "Preferiría Toyota o Honda, pero no es obligatorio. No quiero pickup, no quiero Kia ni Nissan, "
        "y tampoco quiero un carro demasiado pequeño. Somos 4 y llevamos bastante equipaje cuando viajamos."
    ))
    assert c["require_transmission"] == "automatic"
    assert "pickup" in c["avoid_body"]
    assert set(c["avoid_brands"]) >= {"Kia", "Nissan"}
    assert set(c["prefer_brands"]) >= {"Toyota", "Honda"}
    assert c["avoid_small"] is True
    assert c["luggage"] is True
    assert c["passengers"] == 4
    assert v40.v39._should_retrieve(c) is True
    assert v40.v39._hard_ok(_card("Nissan", "Frontier", body="pickup"), c) is False
    assert v40.v39._hard_ok(_card("Ford", "Ranger", body="pickup"), c) is False
    assert v40.v39._hard_ok(_card("Honda", "HR-V"), c) is True


def test_crv_is_strong_exact_and_fallback_is_brand_limited():
    c = v40._constraints(_body(
        "Estoy buscando una Honda CRV 2023 o más nueva, automática, máximo US$500 al mes. "
        "Si no hay una CR-V exacta que cumpla, primero dímelo claramente y después puedes enseñarme "
        "máximo 3 alternativas similares de Toyota, Mazda o Subaru. Nada de Nissan."
    ))
    assert c["exact"][:2] == ("Honda", "CR-V")
    assert c["min_year"] == 2023
    assert c["require_transmission"] == "automatic"
    assert set(c["fallback_brands"]) == {"Toyota", "Mazda", "Subaru"}
    assert "Nissan" in c["avoid_brands"]
    assert c["max_alternatives"] == 3
    alt = dict(c)
    alt["exact"] = None
    alt["allowed_brands"] = c["fallback_brands"]
    assert v40.v39._hard_ok(_card("Mazda", "CX-30"), alt) is True
    assert v40.v39._hard_ok(_card("Kia", "Forte", body="sedan"), alt) is False
    assert v40.v39._hard_ok(_card("Nissan", "Rogue"), alt) is False


def test_soft_corolla_civic_equivalent_is_not_exact():
    c = v40._constraints(_body(
        "Necesito un carro para visitar clientes todos los días, unos 60 km diarios, casi todo carretera. "
        "Quiero que sea silencioso, cómodo y confiable. Máximo US$450 al mes. "
        "Prefiero gastar un poco más por un Corolla, Civic o algo equivalente antes que comprar el carro más barato del mercado. "
        "No quiero microcarros."
    ))
    assert c["exact"] is None
    assert set(c["preferred_models"]) == {("Toyota", "Corolla"), ("Honda", "Civic")}
    assert c["avoid_small"] is True
    assert v40.v39._should_retrieve(c) is True


def test_six_passenger_prompt_accepts_real_three_row_vehicle():
    c = v40._constraints(_body(
        "Somos 6, incluyendo dos niños pequeños. Quiero automático, 2022 o más nuevo, "
        "máximo US$18,000 total y máximo US$430 al mes. No pickups, no Nissan, no Kia. "
        "Si ninguna opción cumple todo, no relajes nada sin preguntarme."
    ))
    outlander = _card("Mitsubishi", "Outlander", year=2022, price=15950, monthly=379,
                       raw_payload={"description": {"value": "3 filas de asientos"}})
    explorer = _card("Ford", "Explorer", year=2022, price=16500, monthly=393,
                      description="Ford Explorer XLT. 3 filas de asientos.")
    sport = _card("Mitsubishi", "Outlander Sport", year=2025, price=13950, monthly=332)
    assert v40.v39._mission_ok(outlander, c) is True
    assert v40.v39._mission_ok(explorer, c) is True
    assert v40.v39._mission_ok(sport, c) is False


def test_luggage_for_four_prefers_suv_over_sedan(monkeypatch):
    c = v40._constraints(_body("Somos 4, llevamos bastante equipaje. Automático, máximo US$425 al mes."))
    monkeypatch.setattr(v40.v39, "_ORIG_SCORE", lambda card, constraints: 50.0)
    suv = _card("Honda", "HR-V", body="suv")
    sedan = _card("Toyota", "Corolla", body="sedan")
    assert v40.v39._score(suv, c) > v40.v39._score(sedan, c)
