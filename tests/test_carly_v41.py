from app import main_v41 as v41


def _body(text):
    return {"messages": [{"role": "user", "content": text}], "country": "sv"}


def _card(**extra):
    row = {
        "make": "Mitsubishi",
        "model": "Outlander",
        "year": 2024,
        "price_usd": 16800,
        "monthly_est": 400,
        "body_type": "suv",
        "transmission": "Automática",
        "listing_state": "indexed",
        "is_addressable": True,
        "url": "https://example.test/mitsubishi-outlander-2024",
    }
    row.update(extra)
    return row


def test_six_passenger_rejects_outlander_sport_hidden_in_url(monkeypatch):
    monkeypatch.setattr(v41, "_ORIG_MISSION_OK", lambda card, c: True)
    c = {"passengers": 6}
    sport = _card(
        model="Outlander",
        url="https://example.test/mitsubishi-outlander-sport-2024",
    )
    assert v41._mission_ok(sport, c) is False


def test_six_passenger_rejects_outlander_sport_hidden_in_title(monkeypatch):
    monkeypatch.setattr(v41, "_ORIG_MISSION_OK", lambda card, c: True)
    c = {"passengers": 6}
    sport = _card(title="Mitsubishi Outlander Sport 2025 Edition Trail 4x4")
    assert v41._mission_ok(sport, c) is False


def test_real_outlander_can_continue_through_existing_capacity_gate(monkeypatch):
    monkeypatch.setattr(v41, "_ORIG_MISSION_OK", lambda card, c: True)
    c = {"passengers": 6}
    real = _card(
        year=2022,
        description="Mitsubishi Outlander ES 2022 con tercera fila de asientos",
        url="https://example.test/mitsubishi-outlander-es-2022",
    )
    assert v41._mission_ok(real, c) is True


def test_six_passenger_reply_never_says_family_of_five(monkeypatch):
    monkeypatch.setattr(v41, "_ORIG_REPLY", lambda c, top, exact_miss=False: "Para una familia de cinco...")
    reply = v41._reply({"passengers": 6}, [_card()], exact_miss=False)
    assert "6 pasajeros" in reply
    assert "cinco" not in reply.lower()
    assert "3 filas" in reply


def test_prefilter_vision_is_skipped_but_authoritative_scan_remains(monkeypatch):
    calls = {"scan": 0}

    def fake_scan(ranked):
        calls["scan"] += 1
        return 1

    monkeypatch.setattr(v41, "_ORIG_SCAN_UNCACHED", fake_scan)

    token = v41._SKIP_PREFILTER_VISION.set(True)
    try:
        assert v41._scan_uncached_finalists([_card()]) == 0
    finally:
        v41._SKIP_PREFILTER_VISION.reset(token)

    assert v41._scan_uncached_finalists([_card()]) == 1
    assert calls["scan"] == 1


def test_focused_apply_runs_base_with_skip_then_rebuild_without_skip(monkeypatch):
    seen = []

    def fake_base(body, prior):
        seen.append(("base", v41._SKIP_PREFILTER_VISION.get()))
        return {"profile": {"country": "sv"}}

    def fake_rebuild(body, prior, c):
        seen.append(("rebuild", v41._SKIP_PREFILTER_VISION.get()))
        return {"profile": prior.get("profile"), "recommendation_brain": {"version": "v39"}}

    monkeypatch.setattr(v41, "_BASE_APPLY", fake_base)
    monkeypatch.setattr(v41.v39, "_rebuild", fake_rebuild)

    result = v41._focused_apply(_body("test"), {}, {"monthly_max": 400})
    assert result["profile"]["country"] == "sv"
    assert seen == [("base", True), ("rebuild", False)]
