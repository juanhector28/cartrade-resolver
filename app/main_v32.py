"""Carly v32: demo guard for market-price plausibility and hard-constraint-safe Explore.

v31 remains the recommendation engine. v32 tightens the last mile so implausibly
cheap listings cannot surface as recommendations and Explore cannot violate a
buyer's explicit body/transmission/model constraints. It also fixes alternative
labels after an exact-model miss.
"""
from __future__ import annotations

import re
from statistics import median
from typing import Any

from . import main_v31 as v31

app = v31.app
v28 = v31.v28

_ORIG_BODY = v31._body
_ORIG_APPLY = v31._apply

try:
    v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v32-demo-guard"
except Exception:
    pass


def _body(card: dict) -> str:
    """Correct known normalization traps before falling back to v31."""
    make = v28._norm(card.get("make"))
    model = v28._norm(card.get("model"))
    if make == "toyota" and re.search(r"\bcorolla\s+cross\b", model, re.I):
        return "suv"
    if make == "toyota" and re.search(r"\bcorolla\s+(?:im|i-m|hatch(?:back)?)\b", model, re.I):
        return "hatchback"
    return _ORIG_BODY(card)


def _model_key(card: dict) -> tuple[str, str]:
    make = v28._norm(card.get("make"))
    model = v28._norm(card.get("model"))
    exact = v31._canonical_exact(f"{make} {model}")
    if exact:
        model = v28._norm(exact[1])
    else:
        tokens = re.findall(r"[a-z0-9]+", model)
        model = tokens[0] if tokens else model
    return make, model


def _price_anomaly(card: dict, rows: list[dict]) -> bool:
    """Return True only for obvious bargain-shaped data anomalies.

    This is intentionally conservative. The goal is not to estimate market value,
    only to keep absurd prices in verification territory rather than Top 3/Explore.
    """
    price = v28._num(card.get("price_usd"))
    year = v28._num(card.get("year"))
    if price is None or price <= 0 or year is None:
        return False

    # Absolute sanity floors catch the $500 Sentra / $1,200 RAV4 class immediately.
    if year >= 2020 and price < 2500:
        return True
    if year >= 2015 and price < 1000:
        return True

    make_key, model_key = _model_key(card)
    peers: list[float] = []
    for other in rows:
        if _model_key(other) != (make_key, model_key):
            continue
        oy = v28._num(other.get("year"))
        op = v28._num(other.get("price_usd"))
        if oy is None or op is None or op <= 0:
            continue
        if abs(float(oy) - float(year)) > 3:
            continue
        peers.append(float(op))

    if len(peers) >= 3:
        peer_median = float(median(peers))
        # A listing less than 45% of a healthy peer median is not a normal bargain.
        if peer_median >= 4000 and price < peer_median * 0.45 and peer_median - price >= 3500:
            return True
    return False


def _rank_rows(rows: list[dict], c: dict[str, Any]) -> tuple[list[dict], int]:
    usable: list[dict] = []
    filtered = 0
    for row in rows:
        row["monthly_est"] = v31._monthly(row)
        if not v31._hard_ok(row, c) or not v31._quality_ok(row) or not v31._mission_ok(row, c):
            filtered += 1
            continue
        if _price_anomaly(row, rows):
            filtered += 1
            continue
        usable.append(row)

    usable = v28._dedupe(usable, {str(r.get("url")): r for r in usable})
    ranked = sorted(usable, key=lambda r: v31._score(r, c), reverse=True)
    return ranked, filtered


def _effective_constraints(c: dict[str, Any], exact_miss: bool) -> dict[str, Any]:
    if not exact_miss or not c.get("exact"):
        return c
    alt = dict(c)
    exact = alt.get("exact")
    alt["exact"] = None
    if exact and not alt.get("require_body"):
        alt["require_body"] = exact[2]
    return alt


def _apply(body: Any, prior_result: Any) -> Any:
    result = _ORIG_APPLY(body, prior_result)
    if not isinstance(result, dict):
        return result
    brain = result.get("recommendation_brain")
    if not isinstance(brain, dict) or brain.get("version") != "v31":
        return result

    c = v31._constraints(body)
    exact_miss = bool(brain.get("exact_miss"))
    effective = _effective_constraints(c, exact_miss)

    # Belt-and-suspenders: every surfaced card, including Explore, must still pass
    # the same hard/mission/quality gates as recommendations.
    surfaced = list(result.get("recommendations") or []) + list(result.get("explore") or [])
    clean: list[dict] = []
    seen: set[str] = set()
    for card in surfaced:
        key = str(card.get("url") or card.get("id") or f"{card.get('make')}:{card.get('model')}:{card.get('year')}:{card.get('price_usd')}")
        if key in seen:
            continue
        seen.add(key)
        if not v31._hard_ok(card, effective) or not v31._quality_ok(card) or not v31._mission_ok(card, effective):
            continue
        clean.append(card)

    top = clean[:3]
    rest = clean[3:12]

    if exact_miss and top:
        labels = ["Alternativa más cercana", "Segunda alternativa", "Otra opción razonable"]
        for idx, card in enumerate(top):
            card["best_for"] = labels[min(idx, len(labels) - 1)]
            card["strategy_label"] = labels[min(idx, len(labels) - 1)]

    result["recommendations"] = top
    result["explore"] = rest
    result["favorite"] = top[0] if top else None
    result["recommendation_count"] = len(top)
    result["explore_count"] = len(rest)
    result["loaded_options"] = top + rest
    result["loaded_option_count"] = len(top) + len(rest)
    result["advisor_mode"] = "recommendation_brain_v32"

    brain["version"] = "v32"
    brain["market_price_plausibility_gate"] = True
    brain["explore_hard_constraints"] = True
    result["recommendation_brain"] = brain

    decision = result.get("decision")
    if isinstance(decision, dict):
        decision.update({"recommendations": list(top), "explore": list(rest), "favorite": result["favorite"]})
    return result


# The route installed by v31 resolves these module globals at request time, so
# replacing them here upgrades the live route without duplicating the full stack.
v31._body = _body
v31._rank_rows = _rank_rows
v31._apply = _apply
