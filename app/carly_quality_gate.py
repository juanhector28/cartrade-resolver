"""Deterministic recommendation quality gate for Carly.

The ranking model should never be allowed to rescue obviously incompatible or
misclassified inventory.  This layer is intentionally cheap: no LLM or vision
calls are made here.  It corrects a few high-confidence body-type mistakes from
model names and applies a conservative pre-rank gate for explicit compact-city
journeys.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable

VISUAL_DAMAGE_THRESHOLD = 0.50
MIN_LISTING_QUALITY = 45.0


def _norm(value: Any) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _canon_body(value: Any) -> str:
    v = _norm(value)
    aliases = {
        "hatch": "hatchback", "hb": "hatchback", "compacto": "hatchback",
        "saloon": "sedan",
        "sport utility": "suv", "todo terreno": "suv", "todoterreno": "suv",
        "camioneta": "suv", "jeepeta": "suv", "yipeta": "suv", "cuv": "crossover",
        "pick up": "pickup", "pick-up": "pickup", "picap": "pickup",
        "troca": "pickup", "palangana": "pickup", "doble cabina": "pickup",
        "van": "minivan", "minibus": "minivan", "microbus": "minivan",
    }
    return aliases.get(v, v)


# High-confidence utility/commercial model families.  These are used only to
# override clearly bad DB body labels such as L200="sedan" or Saveiro="sedan".
_PICKUP_MODELS = re.compile(
    r"\b(?:hilux|hi lux|frontier|ranger|tacoma|d max|dmax|l200|np300|"
    r"ridgeline|colorado|tundra|titan|gladiator|dakota|hardbody|bt 50|"
    r"amarok|sierra|silverado|navara|triton|wingle|alaskan|maverick|"
    r"f 150|f150|f 250|f250|raptor|saveiro|ram 1500)\b",
    re.I,
)
_COMMERCIAL_MODELS = re.compile(
    r"\b(?:hfc\w*|k2700|k2500|npr|nqr|dutro|canter|jac hfc|"
    r"hiace|hi ace|urvan|transit|starex|h 1|h1|sprinter)\b",
    re.I,
)


def semantic_body(car: dict) -> str:
    """Return a high-confidence body label, correcting obvious model mistakes."""
    blob = _norm(" ".join(str(car.get(k) or "") for k in ("make", "model")))
    if _PICKUP_MODELS.search(blob):
        return "pickup"
    if _COMMERCIAL_MODELS.search(blob):
        # HFC/K-series/NPR are commercial vehicles; vans are grouped here because
        # neither belongs in a compact-city shortlist.
        return "commercial"
    return _canon_body(car.get("body_type"))


def normalize_car(car: dict) -> dict:
    out = dict(car or {})
    body = semantic_body(out)
    if body:
        out["body_type"] = body
    return out


def _profile_bodies(profile: Any, field: str) -> set[str]:
    return {_canon_body(x) for x in (getattr(profile, field, None) or []) if x}


def is_explicit_compact_city_profile(profile: Any) -> bool:
    """Recognize the profile emitted for an explicit compact-city request.

    `prefer_body=[hatchback, sedan]` is only emitted by the deterministic parser
    when the buyer actually says compact/compacto, so it is safe to make the
    incompatibility gate hard here even though the general ranker treats prefers
    softly.
    """
    if getattr(profile, "primary_job", None) != "city_runabout":
        return False
    bodies = _profile_bodies(profile, "prefer_body") | _profile_bodies(profile, "require_body")
    return bool({"hatchback", "sedan"} & bodies)


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def eligible_for_profile(car: dict, profile: Any) -> bool:
    """Cheap pre-rank eligibility gate.  Unknown signals do not cause rejection."""
    c = normalize_car(car)

    risk = _num(c.get("visible_damage_risk"))
    if risk is not None and risk >= VISUAL_DAMAGE_THRESHOLD:
        return False

    quality = _num(c.get("quality_score"))
    if quality is not None and quality < MIN_LISTING_QUALITY:
        return False

    # Do not recommend a listing with no usable visual at all. This is a product
    # quality rule, not a claim about vehicle condition.
    if not c.get("primary_photo") and not c.get("photos"):
        return False

    if is_explicit_compact_city_profile(profile):
        if semantic_body(c) not in {"hatchback", "sedan"}:
            return False

    return True


def filter_pool(cars: list[dict], profile: Any) -> list[dict]:
    out = []
    for car in cars or []:
        if not isinstance(car, dict):
            continue
        normalized = normalize_car(car)
        if eligible_for_profile(normalized, profile):
            out.append(normalized)
    return out


def install_rank_quality(original_rank: Callable) -> Callable:
    """Wrap `rank_cars` once so every Carly chat path gets the same gate."""
    if getattr(original_rank, "_carly_quality_wrapped", False):
        return original_rank

    def quality_rank(cars, profile, *args, **kwargs):
        return original_rank(filter_pool(list(cars or []), profile), profile, *args, **kwargs)

    quality_rank._carly_quality_wrapped = True
    quality_rank._carly_original_rank = original_rank
    return quality_rank


def filter_cards(cards: list[dict], profile: Any, limit: int | None = None) -> list[dict]:
    """Final UI safety net for already-built cards."""
    out = []
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        normalized = normalize_car(card)
        if eligible_for_profile(normalized, profile):
            out.append(normalized)
        if limit is not None and len(out) >= limit:
            break
    return out
