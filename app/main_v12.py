"""Carly v12: presentation hierarchy + final semantic incompatibility invariant.

This layer is intentionally tiny. v11 remains responsible for intake, curation and
vehicle briefs. v12 only guarantees that obvious incompatible vehicle families can
never survive into a city shortlist, and formats deterministic brief section labels
for the frontend's existing markdown renderer. No LLM calls are introduced.
"""
from __future__ import annotations

import re
from typing import Any

from . import main_v11 as v11

app = v11.app
commercial = v11.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v12-ui-contract-hotfix"

# Raw marketplace model strings are inconsistent: L200, L 200 and L-200 all occur.
# Keep this final invariant independent of body_type because raw metadata can call a
# pickup a sedan.
_CITY_HARD_EXCLUDE = re.compile(
    r"\b(?:l\s*200|hilux|hi\s*lux|ranger|tacoma|frontier|d\s*max|dmax|np\s*300|"
    r"amarok|navara|triton|colorado|tundra|titan|gladiator|silverado|sierra|"
    r"f\s*150|f\s*250|ram\s*1500|saveiro)\b",
    re.I,
)


def _is_city_profile(result: dict) -> bool:
    try:
        profile = v11.v10._profile_from_result(result)
    except Exception:
        profile = None
    return bool(profile is not None and getattr(profile, "primary_job", None) == "city_runabout")


def _hard_incompatible(card: dict) -> bool:
    blob = " ".join(str(card.get(k) or "") for k in ("make", "model"))
    return bool(_CITY_HARD_EXCLUDE.search(blob))


def _enforce_city_invariant(result: Any) -> Any:
    if not isinstance(result, dict) or result.get("phase") != "recommendation" or not _is_city_profile(result):
        return result

    strong = [c for c in list(result.get("recommendations") or []) if isinstance(c, dict) and not _hard_incompatible(c)]
    explore = [c for c in list(result.get("explore") or []) if isinstance(c, dict) and not _hard_incompatible(c)]
    result["recommendations"] = strong[: v11.MAX_STRONG]
    result["explore"] = explore[: v11.MAX_EXPLORE]
    result["favorite"] = result["recommendations"][0] if result["recommendations"] else None
    result["recommendation_count"] = len(result["recommendations"])
    result["explore_count"] = len(result["explore"])
    result["hard_semantic_invariant"] = "city_no_pickups"
    decision = result.get("decision")
    if isinstance(decision, dict):
        decision["recommendations"] = list(result["recommendations"])
        decision["explore"] = list(result["explore"])
        decision["favorite"] = result["favorite"]
    return result


def _bold_brief_labels(result: Any) -> Any:
    if not isinstance(result, dict) or result.get("advisor_mode") != "verification_vehicle_brief_v11":
        return result
    reply = str(result.get("reply") or "")
    labels = ("MI LECTURA", "POR QUÉ ME GUSTA", "OJO CON", "CARTRADE LO VERIFICA")
    for label in labels:
        # Idempotent so a future native renderer can send markdown already.
        reply = re.sub(rf"(?m)^(?!\*\*){re.escape(label)}(?=\s*[·:-])", f"**{label}**", reply)
    result["reply"] = reply
    result["render_hint"] = "sectioned_advisor_brief_bold"
    return result


def _patch_v12_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue
        prior = endpoint

        def v12_endpoint(*args: Any, __prior=prior, **kwargs: Any):
            result = __prior(*args, **kwargs)
            result = _enforce_city_invariant(result)
            return _bold_brief_labels(result)

        route.endpoint = v12_endpoint
        dependant.call = v12_endpoint
        break


_patch_v12_route()
