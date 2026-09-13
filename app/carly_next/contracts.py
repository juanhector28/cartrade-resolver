from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

@dataclass(frozen=True)
class Provenance:
    source: str
    message_index: int | None = None
    raw: str | None = None

@dataclass(frozen=True)
class Fact:
    value: Any
    provenance: Provenance

@dataclass(frozen=True)
class BuyerState:
    hard: dict[str, Fact] = field(default_factory=dict)
    soft: dict[str, float] = field(default_factory=dict)
    use_cases: frozenset[str] = field(default_factory=frozenset)
    exclusions: dict[str, frozenset[str]] = field(default_factory=dict)
    market: dict[str, Any] = field(default_factory=dict)
    revision: int = 0

    def with_hard(self, key: str, value: Any, provenance: Provenance) -> "BuyerState":
        hard = dict(self.hard)
        hard[key] = Fact(value=value, provenance=provenance)
        return replace(self, hard=hard, revision=self.revision + 1)

    def value(self, key: str, default: Any = None) -> Any:
        fact = self.hard.get(key)
        return fact.value if fact is not None else default

@dataclass(frozen=True)
class CarlyRequest:
    messages: tuple[dict[str, str], ...]
    market: dict[str, Any]
    shown_vehicle_ids: tuple[str, ...] = ()
    session_id: str | None = None

@dataclass(frozen=True)
class SearchPlan:
    country: str
    make: tuple[str, ...] = ()
    body_type: tuple[str, ...] = ()
    min_price: float | None = None
    max_price: float | None = None
    max_monthly: float | None = None
    min_year: int | None = None
    transmission: str | None = None
    served_only: bool = True
    fresh_only: bool = True

@dataclass(frozen=True)
class Candidate:
    id: str
    make: str
    model: str
    year: int | None
    price_usd: float | None
    monthly_est: float | None
    km: float | None
    body_type: str | None
    transmission: str | None = None
    quality_score: float = 0.0
    vehicle_traits: dict[str, float] = field(default_factory=dict)
    served: bool = True
    fresh: bool = True
    indexed: bool = True
    addressable: bool = True
    source: str | None = None

@dataclass(frozen=True)
class RankedCandidate:
    candidate: Candidate
    score: float
    reasons: tuple[str, ...] = ()

@dataclass(frozen=True)
class RequestReceipt:
    request_id: str
    route: str
    buyer_state_revision: int
    retrieved: int = 0
    eligible: int = 0
    served: int = 0
    ranking_policy: str | None = None
    llm_calls: int = 0
    vision_calls: int = 0

@dataclass(frozen=True)
class CarlyResponse:
    phase: str
    reply: str
    recommendations: tuple[RankedCandidate, ...] = ()
    receipt: RequestReceipt | None = None
    buyer_state: BuyerState | None = None
