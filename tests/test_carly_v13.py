from app import main_v13


def test_city_truth_rejects_spaced_l200_from_raw_profile():
    mirage = {"make":"Mitsubishi","model":"Mirage","year":2024,"body_type":"hatchback","url":"1"}
    l200 = {"make":"Mitsubishi","model":"L 200","year":2025,"body_type":"sedan","url":"2"}
    result = {
        "phase":"recommendation",
        "profile":{"primary_job":"city_runabout","prefer_body":["hatchback","sedan"]},
        "recommendations":[mirage],
        "explore":[l200],
        "decision":{"recommendations":[mirage],"explore":[l200]},
    }
    out = main_v13._enforce_city_truth(result)
    assert [c["model"] for c in out["recommendations"]] == ["Mirage"]
    assert out["explore"] == []
    assert out["quality_candidate_count"] == 1
    assert out["more_options_available"] is False
    assert out["more_options_count"] == 0


def test_city_truth_fallback_recognizes_compact_intent_without_enum(monkeypatch):
    monkeypatch.setattr(main_v13.v12, "_is_city_profile", lambda result: False)
    result = {
        "phase":"recommendation",
        "profile":{"intent_segment":"compact city","prefer_body":["hatchback"]},
        "recommendations":[],
        "explore":[{"make":"Mitsubishi","model":"L-200","body_type":"sedan"}],
    }
    out = main_v13._enforce_city_truth(result)
    assert out["explore"] == []


def test_general_reply_gets_scan_hierarchy_and_no_em_dash():
    result = {
        "phase":"conversation",
        "reply":"Entendido. Puedo comparar esas opciones — sin cambiar tus criterios.",
        "token_path":"deterministic",
        "llm_calls":0,
    }
    out = main_v13._presentation(result)
    assert out["reply"].startswith("**Entendido.**")
    assert "—" not in out["reply"]
    assert out["presentation_policy"]["bold_lead"] is True
    assert out["llm_calls"] == 0


def test_bare_question_is_not_overbolded():
    result = {"phase":"conversation", "reply":"¿Qué cuota mensual te queda cómoda?"}
    out = main_v13._presentation(result)
    assert out["reply"] == "¿Qué cuota mensual te queda cómoda?"


def test_v13_runtime_policy():
    assert main_v13.commercial.RUNTIME_COMPOSITION == "commercial-v13-presentation-market-truth"
