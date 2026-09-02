from app import main_v36 as v36


def test_persisted_numeric_damage_risk_is_hard_veto(monkeypatch):
    monkeypatch.setattr(v36, "_ORIG_HARD_RISK", lambda card, enriched=None: False)
    assert v36._hard_risk({"visible_damage_risk": 0.95}, None) is True
    assert v36._hard_risk({"visible_damage_risk": 0.50}, None) is True
    assert v36._hard_risk({"visible_damage_risk": 0.49}, None) is False


def test_scan_only_uncached_finalists_and_persists(monkeypatch):
    rows = [
        {"id": 1, "primary_photo": "https://example.com/a.jpg", "visible_damage_risk": None, "vision_checked_at": None},
        {"id": 2, "primary_photo": "https://example.com/b.jpg", "visible_damage_risk": 0.1, "vision_checked_at": "2026-09-01T00:00:00Z"},
    ]
    seen = []

    monkeypatch.setattr(v36, "JIT_ENABLED", True)
    monkeypatch.setattr(v36, "JIT_MAX_LISTINGS", 3)
    monkeypatch.setattr(v36, "_vision_result", lambda row: {"visible_damage_risk": 0.88, "signals": ["panel desalineado"]})

    def fake_persist(row, result):
        seen.append(row["id"])
        row.update(result)
        row["vision_checked_at"] = "now"

    monkeypatch.setattr(v36, "_persist", fake_persist)
    assert v36._scan_uncached_finalists(rows) == 1
    assert seen == [1]
    assert rows[0]["visible_damage_risk"] == 0.88


def test_rank_reruns_after_vision_and_removes_damaged(monkeypatch):
    rows = [
        {"id": 1, "primary_photo": "https://example.com/a.jpg", "visible_damage_risk": None, "vision_checked_at": None},
        {"id": 2, "primary_photo": "https://example.com/b.jpg", "visible_damage_risk": 0.1, "vision_checked_at": "done"},
    ]
    calls = {"n": 0}

    def fake_rank(input_rows, constraints):
        calls["n"] += 1
        eligible = [r for r in input_rows if v36._risk(r.get("visible_damage_risk")) is None or v36._risk(r.get("visible_damage_risk")) < 0.5]
        return eligible, len(input_rows) - len(eligible)

    def fake_scan(ranked):
        rows[0]["visible_damage_risk"] = 0.92
        rows[0]["vision_checked_at"] = "now"
        return 1

    monkeypatch.setattr(v36, "_ORIG_RANK_ROWS", fake_rank)
    monkeypatch.setattr(v36, "_scan_uncached_finalists", fake_scan)
    ranked, filtered = v36._rank_rows(rows, {})
    assert calls["n"] == 2
    assert [r["id"] for r in ranked] == [2]
    assert filtered == 1


def test_parse_requires_signal_for_high_damage_score():
    assert v36._parse_result('{"visible_damage_risk":0.9,"signals":[]}')["visible_damage_risk"] == 0.49
    parsed = v36._parse_result('{"visible_damage_risk":0.9,"signals":["bumper desprendido"]}')
    assert parsed["visible_damage_risk"] == 0.9
