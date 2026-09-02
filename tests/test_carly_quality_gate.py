from types import SimpleNamespace

from app.carly_quality_gate import (
    eligible_for_profile,
    filter_cards,
    install_rank_quality,
    semantic_body,
)


def _compact_profile():
    return SimpleNamespace(
        primary_job="city_runabout",
        prefer_body=["hatchback", "sedan"],
        require_body=[],
    )


def _car(model, body="sedan", quality=80, **extra):
    row = {
        "make": extra.pop("make", "Kia"),
        "model": model,
        "body_type": body,
        "quality_score": quality,
        "primary_photo": "https://img.test/car.jpg",
    }
    row.update(extra)
    return row


def test_semantic_body_corrects_obvious_bad_db_labels():
    assert semantic_body(_car("L200", make="Mitsubishi")) == "pickup"
    assert semantic_body(_car("Saveiro", make="Volkswagen")) == "pickup"
    assert semantic_body(_car("HFC", make="JAC")) == "commercial"


def test_compact_city_gate_rejects_pickups_and_commercial_vehicles():
    p = _compact_profile()
    assert eligible_for_profile(_car("Picanto", body="hatchback"), p)
    assert not eligible_for_profile(_car("L200", make="Mitsubishi"), p)
    assert not eligible_for_profile(_car("Saveiro", make="Volkswagen"), p)
    assert not eligible_for_profile(_car("HFC", make="JAC"), p)


def test_visible_damage_and_low_listing_quality_do_not_surface():
    p = _compact_profile()
    assert not eligible_for_profile(_car("Picanto", body="hatchback", visible_damage_risk=0.72), p)
    assert not eligible_for_profile(_car("Picanto", body="hatchback", quality=20), p)


def test_final_cards_never_fill_with_incompatible_inventory():
    p = _compact_profile()
    cards = [
        _car("Picanto", body="hatchback"),
        _car("Swift", body="hatchback", make="Suzuki"),
        _car("Fit", body="hatchback", make="Honda"),
        _car("L200", make="Mitsubishi"),
        _car("Saveiro", make="Volkswagen"),
    ]
    out = filter_cards(cards, p, limit=3)
    assert [c["model"] for c in out] == ["Picanto", "Swift", "Fit"]


def test_rank_wrapper_filters_before_scoring():
    p = _compact_profile()
    seen = []

    def fake_rank(cars, profile, top_n=6):
        seen.extend(cars)
        return cars[:top_n]

    wrapped = install_rank_quality(fake_rank)
    wrapped([
        _car("Picanto", body="hatchback"),
        _car("L200", make="Mitsubishi"),
    ], p, top_n=6)
    assert [c["model"] for c in seen] == ["Picanto"]


def test_one_off_live_carly_comparison_probe():
    import json
    import urllib.request

    prompt = "Necesito un carro cómodo para ir a la universidad. Manejo unos 20 km al día y no quiero pagar más de US$500 al mes."
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "country": "sv",
        "top_n": 6,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://cartrade-resolver.onrender.com/carly/chat",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "CarTrade-Carly-Compare/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    print("CARLY_COMPARE_RESULT=" + json.dumps(data, ensure_ascii=False))
    assert isinstance(data, dict)
