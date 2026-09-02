from app import main_v37 as v37


def _body(text):
    return {"messages": [{"role": "user", "content": text}], "country": "sv"}


def test_no_pickup_is_negation_not_requirement():
    c = v37._constraints(_body(
        "Somos 5. Necesito algo para finca. No quiero pickup bajo ninguna circunstancia. "
        "Automática, máximo US$450 al mes."
    ))
    assert c["require_body"] is None
    assert "pickup" in c["avoid_body"]
    assert c["require_transmission"] == "automatic"


def test_nuclear_prompt_preserves_compact_year_total_budget_and_brands():
    c = v37._constraints(_body(
        "Somos 6, incluyendo dos niños pequeños. Quiero algo automático 2023+, cómodo para viajes largos, "
        "máximo US$400 al mes y US$17,000 total. No pickup, no Nissan, no Kia. "
        "Prefiero Toyota u Honda, pero acepto otras marcas confiables. "
        "Si ninguna opción cumple todo, no relajes nada sin preguntarme primero."
    ))
    assert c["min_year"] == 2023
    assert c["total_budget"] == 17000
    assert "pickup" in c["avoid_body"]
    assert set(c["avoid_brands"]) >= {"Nissan", "Kia"}
    assert set(c["prefer_brands"]) >= {"Toyota", "Honda"}
    assert c["passengers"] == 6
    assert c["strict_no_relax"] is True


def test_avoid_body_and_brand_are_hard_filters():
    c = v37._constraints(_body(
        "No pickup, no Nissan. Automática, máximo US$450 al mes. Somos 5."
    ))
    pickup = {"make": "Toyota", "model": "Tacoma", "year": 2023, "price_usd": 15000,
              "monthly_est": 350, "body_type": "pickup", "transmission": "Automática",
              "listing_state": "indexed", "is_addressable": True}
    nissan = {"make": "Nissan", "model": "Rogue", "year": 2023, "price_usd": 15000,
              "monthly_est": 350, "body_type": "suv", "transmission": "Automática",
              "listing_state": "indexed", "is_addressable": True}
    toyota = {"make": "Toyota", "model": "RAV4", "year": 2023, "price_usd": 15000,
              "monthly_est": 350, "body_type": "suv", "transmission": "Automática",
              "listing_state": "indexed", "is_addressable": True}
    assert v37._hard_ok(pickup, c) is False
    assert v37._hard_ok(nissan, c) is False
    assert v37._hard_ok(toyota, c) is True


def test_six_passengers_rejects_five_seat_compact_suv():
    c = v37._constraints(_body(
        "Somos 6. Quiero algo automático 2023+, máximo US$400 al mes."
    ))
    outlander_sport = {"make": "Mitsubishi", "model": "Outlander Sport", "year": 2023,
                       "body_type": "suv", "transmission": "Automática", "listing_state": "indexed",
                       "is_addressable": True, "price_usd": 15000, "monthly_est": 350}
    highlander = {"make": "Toyota", "model": "Highlander", "year": 2023,
                  "body_type": "suv", "transmission": "Automática", "listing_state": "indexed",
                  "is_addressable": True, "price_usd": 15000, "monthly_est": 350}
    assert v37._mission_ok(outlander_sport, c) is False
    assert v37._mission_ok(highlander, c) is True


def test_strict_no_relax_empty_reply_does_not_offer_silent_relaxation():
    c = v37._constraints(_body(
        "Pickup pequeña, 5 adultos, automática 2022+, máximo US$300. No quiero sacrificar nada."
    ))
    reply = v37._reply(c, [], exact_miss=False)
    assert "No relajé ninguna" in reply


def test_download_image_rejects_non_image_or_failure(monkeypatch):
    class Response:
        content = b"abc"
        headers = {"content-type": "application/octet-stream"}
        def raise_for_status(self): pass
    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, url): return Response()
    monkeypatch.setattr(v37.httpx, "Client", Client)
    media, data = v37._download_image("https://example.com/car.jpg")
    assert media == "image/jpeg"
    assert data
