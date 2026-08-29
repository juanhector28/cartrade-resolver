from types import SimpleNamespace

from app import main_v12


def city_profile():
    return SimpleNamespace(primary_job="city_runabout", prefer_body=["hatchback", "sedan"], require_body=[], max_monthly=500)


def test_city_invariant_rejects_spaced_l200_even_if_mislabeled_sedan(monkeypatch):
    monkeypatch.setattr(main_v12.v11.v10, "_profile_from_result", lambda result: city_profile())
    mirage = {"make":"Mitsubishi","model":"Mirage","year":2024,"body_type":"hatchback","url":"1"}
    l200 = {"make":"Mitsubishi","model":"L 200","year":2025,"body_type":"sedan","url":"2"}
    result = {
        "phase":"recommendation",
        "profile":{},
        "recommendations":[mirage],
        "explore":[l200],
        "decision":{"recommendations":[mirage],"explore":[l200]},
    }
    out = main_v12._enforce_city_invariant(result)
    assert [c["model"] for c in out["recommendations"]] == ["Mirage"]
    assert out["explore"] == []
    assert out["decision"]["explore"] == []
    assert out["hard_semantic_invariant"] == "city_no_pickups"


def test_vehicle_brief_labels_are_markdown_bold_without_llm():
    result = {
        "phase":"conversation",
        "advisor_mode":"verification_vehicle_brief_v11",
        "llm_calls":0,
        "token_path":"deterministic_vehicle_brief",
        "reply":"MI LECTURA · Sí.\n\nPOR QUÉ ME GUSTA · Encaja.\n\nOJO CON · Revisa.\n\nCARTRADE LO VERIFICA · Documentos.",
    }
    out = main_v12._bold_brief_labels(result)
    assert "**MI LECTURA** ·" in out["reply"]
    assert "**POR QUÉ ME GUSTA** ·" in out["reply"]
    assert "**OJO CON** ·" in out["reply"]
    assert "**CARTRADE LO VERIFICA** ·" in out["reply"]
    assert out["llm_calls"] == 0
    assert out["token_path"] == "deterministic_vehicle_brief"


def test_v12_runtime_policy():
    assert main_v12.commercial.RUNTIME_COMPOSITION == "commercial-v12-ui-contract-hotfix"
