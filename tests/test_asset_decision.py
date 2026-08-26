from app.asset_decision import (
    AcquirerNeedModel,
    AssetEvidence,
    Constraint,
    DecisionRecord,
    DecisionScores,
    DecisionState,
    EvidenceItem,
    EvidenceKind,
    NextBestAction,
    choose_next_best_action,
    confidence_score,
    dominates,
    pareto_frontier,
    readiness_score,
)


def test_hard_constraints_fail_closed_when_fact_is_missing():
    need = AcquirerNeedModel(
        asset_class="vehicle",
        hard_constraints=[
            Constraint("price_usd", "<=", 12000),
            Constraint("km", "<=", 65000),
        ],
    )
    assert need.passes_hard_constraints({"price_usd": 11000, "km": 50000})
    assert not need.passes_hard_constraints({"price_usd": 11000})
    assert not need.passes_hard_constraints({"price_usd": 13000, "km": 50000})


def test_evidence_separates_unknown_from_asserted_facts():
    ev = AssetEvidence("v1", "vehicle")
    ev.put(EvidenceItem("price_usd", 10500, EvidenceKind.KNOWN, source="listing"))
    ev.put(EvidenceItem("market_delta_pct", 3.2, EvidenceKind.DERIVED, source="market_engine"))
    ev.put(EvidenceItem("accident_history", None, EvidenceKind.UNKNOWN))
    ev.put(EvidenceItem("title", "clean", EvidenceKind.VERIFIED, source="registry"))

    assert ev.known_value("price_usd") == 10500
    assert ev.known_value("accident_history") is None
    assert ev.unknown_keys() == ["accident_history"]
    assert confidence_score(ev) == 65.0


def test_readiness_requires_verified_close_fields():
    ev = AssetEvidence("v1", "vehicle")
    ev.put(EvidenceItem("identity", "ok", EvidenceKind.VERIFIED))
    ev.put(EvidenceItem("title", "clean", EvidenceKind.VERIFIED))
    ev.put(EvidenceItem("condition", None, EvidenceKind.UNKNOWN))
    assert readiness_score(ev, {"identity", "title", "condition"}) == 66.7
    assert choose_next_best_action(ev, {"identity", "title", "condition"}) == NextBestAction.INSPECT


def test_pareto_dominance_is_multi_dimensional_not_magic_score():
    a = DecisionRecord(
        "a", DecisionScores(92, 85, 80, 70), DecisionState.CONTENDER
    )
    b = DecisionRecord(
        "b", DecisionScores(88, 80, 75, 65), DecisionState.CONTENDER
    )
    c = DecisionRecord(
        "c", DecisionScores(95, 60, 90, 55), DecisionState.CONTENDER
    )

    assert dominates(a, b)
    assert not dominates(a, c)
    assert {r.asset_id for r in pareto_frontier([a, b, c])} == {"a", "c"}
