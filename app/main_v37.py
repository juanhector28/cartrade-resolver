"""Carly v37: negation-safe constraints, six-seat gating, fresh decisions and robust JIT vision.

Fixes demo-visible failures from the spicy production repro:
- `no pickup` must never become `require pickup`;
- parse compact years such as `2023+` and total budgets such as `US$17,000 total`;
- preserve explicit excluded/preferred brands;
- fail closed on passenger capacity for 6+ unless seating capacity is evidenced;
- rebuild Decision Room from the final v37 shortlist so stale earlier decisions cannot survive;
- download finalist images server-side and send base64 to vision, avoiding remote-image fetch failures.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any

import httpx

from . import carly_decision_room
from . import main_v36 as v36

app = v36.app
v35 = v36.v35
v34 = v36.v34
v33 = v34.v33
v31 = v36.v31
v28 = v36.v28
legacy = v36.legacy

_ORIG_CONSTRAINTS = v31._constraints
_ORIG_HARD_OK = v31._hard_ok
_ORIG_MISSION_OK = v31._mission_ok
_ORIG_REPLY = v31._reply
_ORIG_APPLY = v31._apply

try:
    v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v37-spicy-hardening"
except Exception:
    pass

# Six fresh finalist images is still tiny, and every successful result is persisted.
v36.JIT_MAX_LISTINGS = max(v36.JIT_MAX_LISTINGS, 6)

_NO_PICKUP = re.compile(
    r"\b(?:no\s+(?:quiero|quisiera|acepto|busco|necesito)?\s*|sin\s+|nada\s+de\s+)"
    r"(?:una?\s+)?(?:pickup|pick[- ]?up)\b",
    re.I,
)
_YEAR_PLUS = re.compile(r"\b(20\d{2})\s*\+", re.I)
_STRICT_NO_RELAX = re.compile(
    r"\b(?:no\s+(?:quiero\s+)?sacrificar|no\s+relajes?|sin\s+relajar|"
    r"no\s+cambies?|no\s+aflojes?|sin\s+preguntarme\s+primero)\b",
    re.I,
)
_NO_DAMAGE = re.compile(
    r"\b(?:no\s+quiero\s+carros?\s+(?:chocados?|reparados?)|sin\s+da[nñ]o\s+visible|"
    r"no\s+.*?da[nñ]o\s+visible|no\s+.*?salvage|no\s+.*?chocados?)\b",
    re.I,
)

# Known families where a six-person request is at least physically plausible.
# We stay conservative: unknown five-seat crossovers are rejected for 6+.
_SIX_PLUS_MODELS = re.compile(
    r"\b(?:highlander|sequoia|sienna|pilot|odyssey|pathfinder|armada|palisade|"
    r"santa\s*fe|telluride|sorento|carnival|outlander(?!\s+sport)|cx[- ]?9|cx[- ]?90|"
    r"explorer|expedition|traverse|tahoe|suburban|durango|grand\s+cherokee\s+l|"
    r"land\s+cruiser|prado|fortuner|everest|montero|pajero|q7|xc90|x7|gls)\b",
    re.I,
)
_SEATING_EVIDENCE = re.compile(
    r"\b(?:6|7|8)\s*(?:pasajeros|asientos|plazas)|\b(?:tercera|3a|3ra)\s+fila\b|"
    r"\bthird\s+row\b|\b(?:6|7|8)[- ]?seater\b",
    re.I,
)

_BRAND_PATTERN = "|".join(sorted((re.escape(a) for a in v31._BRAND_ALIASES), key=len, reverse=True))
_NEGATED_BRAND = re.compile(
    rf"\b(?:no(?:\s+(?:quiero|quisiera|acepto|busco|me\s+(?:muestres|ense[nñ]es)))?|ni|sin)\s+"
    rf"(?:marca\s+)?(?P<brand>{_BRAND_PATTERN})\b",
    re.I,
)
_PREFERENCE_CUE = re.compile(r"\b(?:prefiero|preferir[ií]a|de\s+preferencia|idealmente)\b", re.I)


def _canonical_brand(alias: str) -> str | None:
    return v31._BRAND_ALIASES.get(v28._norm(alias))


def _brand_constraints(text: str) -> tuple[list[str], list[str]]:
    avoid: list[str] = []
    for m in _NEGATED_BRAND.finditer(text or ""):
        brand = _canonical_brand(m.group("brand"))
        if brand and brand not in avoid:
            avoid.append(brand)

    prefer: list[str] = []
    for cue in _PREFERENCE_CUE.finditer(text or ""):
        clause = (text or "")[cue.end():cue.end() + 100]
        clause = re.split(r"[.;]", clause, maxsplit=1)[0]
        n = v28._norm(clause)
        for alias, canonical in v31._BRAND_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", n) and canonical not in avoid and canonical not in prefer:
                prefer.append(canonical)
    return avoid, prefer


def _total_budget_after(text: str) -> float | None:
    # Keep v33's robust parser, then add the common `US$17,000 total` suffix form.
    total = v33._explicit_total_budget(text or "")
    if total is not None:
        return total
    candidates: list[float] = []
    for m in v33._MONEY.finditer(text or ""):
        value = v33._money_number(m.group(1), m.group(2))
        if value is None or not (2000 <= value <= 500000):
            continue
        suffix = (text or "")[m.end():m.end() + 28]
        if re.search(r"^\s*(?:de\s+precio\s+)?(?:total|precio\s+total|de\s+contado|al\s+contado)\b", suffix, re.I):
            candidates.append(float(value))
    return candidates[-1] if candidates else None


def _constraints(body: Any) -> dict[str, Any]:
    c = dict(_ORIG_CONSTRAINTS(body))
    text = str(c.get("text") or "")

    avoid_body = list(c.get("avoid_body") or [])
    if _NO_PICKUP.search(text):
        if "pickup" not in avoid_body:
            avoid_body.append("pickup")
        if c.get("require_body") == "pickup":
            c["require_body"] = None
    c["avoid_body"] = avoid_body

    m = _YEAR_PLUS.search(text)
    if m:
        c["min_year"] = max(int(m.group(1)), int(c.get("min_year") or 0))

    total = _total_budget_after(text)
    if total is not None:
        c["total_budget"] = total

    avoid_brands, prefer_brands = _brand_constraints(text)
    c["avoid_brands"] = list(dict.fromkeys(list(c.get("avoid_brands") or []) + avoid_brands))
    c["prefer_brands"] = list(dict.fromkeys(list(c.get("prefer_brands") or []) + prefer_brands))
    c["strict_no_relax"] = bool(_STRICT_NO_RELAX.search(text))
    c["explicit_no_damage"] = bool(_NO_DAMAGE.search(text))
    return c


def _hard_ok(card: dict, c: dict[str, Any]) -> bool:
    if not _ORIG_HARD_OK(card, c):
        return False
    body = v31._body(card)
    if body in set(c.get("avoid_body") or []):
        return False
    make = v28._norm(card.get("make"))
    avoid = {v28._norm(x) for x in (c.get("avoid_brands") or [])}
    if make and make in avoid:
        return False
    return True


def _mission_ok(card: dict, c: dict[str, Any]) -> bool:
    if not _ORIG_MISSION_OK(card, c):
        return False
    passengers = int(c.get("passengers") or 0)
    if passengers >= 6:
        model = str(card.get("model") or "")
        blob = v28._card_blob(card, card)
        if re.search(r"\boutlander\s+sport\b", model, re.I):
            return False
        if not _SEATING_EVIDENCE.search(blob) and not _SIX_PLUS_MODELS.search(model):
            return False
    return True


def _reply(c: dict[str, Any], top: list[dict], exact_miss: bool = False) -> str:
    if not top and c.get("strict_no_relax"):
        return (
            "No encontré una opción que cumpla todas tus condiciones actuales. "
            "No relajé ninguna. Si quieres, dime cuál criterio estás dispuesto a mover primero."
        )
    return _ORIG_REPLY(c, top, exact_miss=exact_miss)


def _download_image(url: str) -> tuple[str, str] | None:
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 CarTradeVision/1.0"}) as cli:
            r = cli.get(url)
            r.raise_for_status()
            data = r.content
            if not data or len(data) > 5_000_000:
                return None
            media = (r.headers.get("content-type") or "image/jpeg").split(";", 1)[0].strip().lower()
            if media not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
                # Infer common formats when CDNs return octet-stream.
                low = url.lower()
                if ".png" in low:
                    media = "image/png"
                elif ".webp" in low:
                    media = "image/webp"
                elif ".gif" in low:
                    media = "image/gif"
                else:
                    media = "image/jpeg"
            return media, base64.b64encode(data).decode("ascii")
    except Exception:
        return None


def _vision_result(row: dict) -> dict | None:
    if not v36.JIT_ENABLED or v36.JIT_MAX_LISTINGS <= 0:
        return None
    client = getattr(legacy, "_anthropic", None)
    photo = v36._photo(row)
    if client is None or not photo:
        return None
    downloaded = _download_image(photo)
    if not downloaded:
        return None
    media_type, data = downloaded
    try:
        resp = client.messages.create(
            model=v36.JIT_MODEL,
            max_tokens=180,
            system=v36._VISION_SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": "Screen this single vehicle photo. Return only JSON."},
                ],
            }],
        )
        text = "".join(
            getattr(block, "text", "") for block in getattr(resp, "content", [])
            if getattr(block, "type", "") == "text"
        )
        return v36._parse_result(text)
    except Exception:
        return None


def _refresh_profile(result: dict, c: dict[str, Any]) -> None:
    profile = dict(result.get("profile") or {})
    if c.get("total_budget") is not None:
        profile["max_price"] = c["total_budget"]
    if c.get("min_year") is not None:
        profile["min_year"] = c["min_year"]
    if c.get("passengers") is not None:
        profile["passengers"] = c["passengers"]
    if c.get("avoid_body"):
        profile["avoid_body"] = list(c["avoid_body"])
    if c.get("avoid_brands"):
        profile["avoid_brands"] = list(c["avoid_brands"])
    if c.get("prefer_brands"):
        profile["prefer_brands"] = list(c["prefer_brands"])
    if c.get("require_transmission") == "automatic":
        profile["avoid_transmission"] = "manual"
    elif c.get("require_transmission") == "manual":
        profile["avoid_transmission"] = "automatic"
    result["profile"] = profile


def _apply(body: Any, prior_result: Any) -> Any:
    result = _ORIG_APPLY(body, prior_result)
    if not isinstance(result, dict):
        return result
    c = _constraints(body)
    _refresh_profile(result, c)

    brain = dict(result.get("recommendation_brain") or {})
    brain.update({
        "version": "v37",
        "negation_safe_body": True,
        "compact_min_year": True,
        "brand_exclusions": True,
        "six_plus_capacity_gate": True,
        "vision_transport": "server_download_base64",
        "vision_jit_max": v36.JIT_MAX_LISTINGS,
    })
    hard = dict(brain.get("hard_constraints") or {})
    hard.update({
        "body": c.get("require_body"),
        "avoid_body": c.get("avoid_body") or [],
        "transmission": c.get("require_transmission"),
        "min_year": c.get("min_year"),
        "monthly_max": c.get("monthly_max"),
        "total_budget": c.get("total_budget"),
        "avoid_brands": c.get("avoid_brands") or [],
        "passengers": c.get("passengers"),
    })
    brain["hard_constraints"] = hard
    result["recommendation_brain"] = brain
    result["advisor_mode"] = "recommendation_brain_v37"

    top = list(result.get("recommendations") or [])
    if not top:
        # A zero-card recommendation page was producing stale cards/locked UI.
        # Keep the user in conversation and explicitly clear any prior decision.
        result["phase"] = "conversation"
        result["favorite"] = None
        result["recommendations"] = []
        result["explore"] = []
        result["recommendation_count"] = 0
        result["explore_count"] = 0
        result["loaded_options"] = []
        result["loaded_option_count"] = 0
        result.pop("decision", None)
        result["decision_room"] = False
    else:
        # Earlier stack layers may have decorated `prior_result` before v31 replaced
        # the shortlist. Rebuild from the final shortlist so Decision Room cannot
        # display a stale vehicle from a previous search.
        result.pop("decision", None)
        result["decision"] = carly_decision_room.build_decision(result, country=profile_country(result, body))
        result["decision_room"] = True
    return result


def profile_country(result: dict, body: Any) -> str | None:
    profile = result.get("profile") or {}
    if profile.get("country"):
        return str(profile.get("country"))
    try:
        value = body.get("country") if isinstance(body, dict) else getattr(body, "country", None)
        return str(value) if value else None
    except Exception:
        return None


# Dynamic globals used by the v31-installed route and the v36 finalist scanner.
v31._constraints = _constraints
v31._hard_ok = _hard_ok
v31._mission_ok = _mission_ok
v31._reply = _reply
v31._apply = _apply
v36._vision_result = _vision_result
