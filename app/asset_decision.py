"""Generic Asset Discovery + Decision core.

This module is intentionally asset-agnostic. CarTrade is the first consumer, but
Atlas should be able to reuse the same contracts for houses, boats, machinery,
energy assets, and other transactable assets.

The core separates:
- buyer/acquirer need facts;
- hard constraints vs soft preferences;
- asset evidence and provenance;
- fit, confidence, value, and execution readiness;
- decision state and next-best action.

The LLM may classify language into these contracts. It does not invent scores.
Scores and decision states are produced by deterministic code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class EvidenceKind(str, Enum):
    KNOWN = "known"
    DERIVED = "derived"
    MODEL_KNOWLEDGE = "model_knowledge"
    UNKNOWN = "unknown"
    VERIFIED = "verified"


class DecisionState(str, Enum):
    DOMINATED = "dominated"
    CONTENDER = "contender"
    RECOMMENDED = "recommended"
    CONDITIONAL_WINNER = "conditional_winner"
    VERIFY_FIRST = "verify_first"
    WAIT = "wait"


class NextBestAction(str, Enum):
    VIEW_DETAILS = "view_details"
    VERIFY = "verify"
    INSPECT = "inspect"
    NEGOTIATE = "negotiate"
    FINANCE = "finance"
    OFFER = "offer"
    CLOSE = "close"
    EXPAND_SEARCH = "expand_search"
    HOLD = "hold"


@dataclass(frozen=True)
class EvidenceItem:
    key: str
    value: Any
    kind: EvidenceKind
    source: str | None = None
    confidence: float | None = None
    verified_at: str | None = None

    def __post_init__(self):
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.kind == EvidenceKind.UNKNOWN and self.value not in (None, "unknown"):
            raise ValueError("unknown evidence cannot carry an asserted value")


@dataclass
class AssetEvidence:
    asset_id: str
    asset_class: str
    items: dict[str, EvidenceItem] = field(default_factory=dict)

    def put(self, item: EvidenceItem) -> None:
        self.items[item.key] = item

    def get(self, key: str) -> EvidenceItem | None:
        return self.items.get(key)

    def known_value(self, key: str, default: Any = None) -> Any:
        item = self.items.get(key)
        if item is None or item.kind == EvidenceKind.UNKNOWN:
            return default
        return item.value

    def unknown_keys(self) -> list[str]:
        return sorted(k for k, v in self.items.items() if v.kind == EvidenceKind.UNKNOWN)

    def evidence_coverage(self) -> float:
        if not self.items:
            return 0.0
        informative = sum(1 for item in self.items.values() if item.kind != EvidenceKind.UNKNOWN)
        return informative / len(self.items)

    def verified_coverage(self) -> float:
        if not self.items:
            return 0.0
        verified = sum(1 for item in self.items.values() if item.kind == EvidenceKind.VERIFIED)
        return verified / len(self.items)


@dataclass(frozen=True)
class Constraint:
    field: str
    operator: str
    value: Any
    source: str = "buyer"

    def passes(self, candidate: Mapping[str, Any]) -> bool:
        actual = candidate.get(self.field)
        if actual is None:
            return False
        if self.operator == "<=":
            return actual <= self.value
        if self.operator == ">=":
            return actual >= self.value
        if self.operator == "==":
            return actual == self.value
        if self.operator == "!=":
            return actual != self.value
        if self.operator == "in":
            return actual in self.value
        if self.operator == "not_in":
            return actual not in self.value
        raise ValueError(f"unsupported constraint operator: {self.operator}")


@dataclass
class AcquirerNeedModel:
    asset_class: str
    primary_job: str | None = None
    secondary_job: str | None = None
    hard_constraints: list[Constraint] = field(default_factory=list)
    soft_preferences: dict[str, float] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    target_budget: float | None = None
    max_budget: float | None = None

    def passes_hard_constraints(self, candidate: Mapping[str, Any]) -> bool:
        return all(c.passes(candidate) for c in self.hard_constraints)


@dataclass(frozen=True)
class DecisionScores:
    fit: float
    confidence: float
    value: float
    readiness: float

    def __post_init__(self):
        for name, value in (
            ("fit", self.fit),
            ("confidence", self.confidence),
            ("value", self.value),
            ("readiness", self.readiness),
        ):
            if not 0 <= value <= 100:
                raise ValueError(f"{name} must be between 0 and 100")


@dataclass
class DecisionRecord:
    asset_id: str
    scores: DecisionScores
    state: DecisionState
    reasons: list[str] = field(default_factory=list)
    tradeoffs: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    next_best_action: NextBestAction = NextBestAction.VIEW_DETAILS
    conditional_on: list[str] = field(default_factory=list)


DEFAULT_CONFIDENCE_WEIGHTS = {
    EvidenceKind.VERIFIED: 1.0,
    EvidenceKind.KNOWN: 0.85,
    EvidenceKind.DERIVED: 0.75,
    EvidenceKind.MODEL_KNOWLEDGE: 0.45,
    EvidenceKind.UNKNOWN: 0.0,
}


def confidence_score(evidence: AssetEvidence, weights: Mapping[EvidenceKind, float] | None = None) -> float:
    """Deterministic evidence-quality score.

    This is intentionally simple for v1. Later calibration can weight evidence
    fields by decision materiality and observed transaction outcomes.
    """
    if not evidence.items:
        return 0.0
    weights = weights or DEFAULT_CONFIDENCE_WEIGHTS
    total = sum(float(weights[item.kind]) for item in evidence.items.values())
    return round(100.0 * total / len(evidence.items), 1)


def readiness_score(evidence: AssetEvidence, required_for_close: set[str]) -> float:
    if not required_for_close:
        return 100.0
    ready = 0
    for key in required_for_close:
        item = evidence.get(key)
        if item and item.kind == EvidenceKind.VERIFIED:
            ready += 1
    return round(100.0 * ready / len(required_for_close), 1)


def dominates(a: DecisionRecord, b: DecisionRecord, tolerance: float = 0.0) -> bool:
    """True when A is no worse on all decision dimensions and better on one.

    This is a Pareto check, not a weighted-score shortcut.
    """
    av = (a.scores.fit, a.scores.confidence, a.scores.value, a.scores.readiness)
    bv = (b.scores.fit, b.scores.confidence, b.scores.value, b.scores.readiness)
    no_worse = all(x + tolerance >= y for x, y in zip(av, bv))
    strictly_better = any(x > y + tolerance for x, y in zip(av, bv))
    return no_worse and strictly_better


def pareto_frontier(records: list[DecisionRecord], tolerance: float = 0.0) -> list[DecisionRecord]:
    frontier: list[DecisionRecord] = []
    for candidate in records:
        if any(other.asset_id != candidate.asset_id and dominates(other, candidate, tolerance) for other in records):
            continue
        frontier.append(candidate)
    return frontier


def choose_next_best_action(evidence: AssetEvidence, required_for_close: set[str]) -> NextBestAction:
    """Pick the first action that reduces the most material unresolved uncertainty."""
    unknowns = set(evidence.unknown_keys())
    verification_fields = {"identity", "ownership", "title", "documents", "liens"}
    inspection_fields = {"condition", "mechanical_condition", "odometer", "damage", "accident_history"}

    if unknowns & verification_fields:
        return NextBestAction.VERIFY
    if unknowns & inspection_fields:
        return NextBestAction.INSPECT
    if readiness_score(evidence, required_for_close) < 100:
        return NextBestAction.VERIFY
    return NextBestAction.CLOSE
