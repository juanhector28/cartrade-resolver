"""Carly v13: presentation hierarchy, truthful option counts, and stronger city invariants.

No paid model calls are added here. This wrapper only post-processes existing
structured responses so presentation remains scan-friendly and the UI never
promises inventory that Carly has already rejected.
"""
from __future__ import annotations

import re
from typing import Any

from . import main_v12 as v12

app = v12.app
commercial = v12.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v13-presentation-market-truth"

_CITY_WORDS_RE = re.compile(r"\b(?:city|ciudad|urbano|compact|estacion|parque|parquear)\b", re.I)
_HARD_PICKUP_RE = re.compile(
    r"\b(?:l\s*[- ]?\s*200|hilux|hi\s*lux|ranger|tacoma|frontier|d\s*max|dmax|np\s*300|"
    r"amarok|navara|triton|colorado|tundra|titan|gladiator|silverado|sierra|"
    r"f\s*150|f\s*250|ram\s*1500|saveiro)\b",
    re.I,
)


def _profile_dict(result: dict) -> dict:
    raw = result.get("profile")
    return dict(raw) if isinstance(raw, dict) else {}


def _city_intent(result: dict) -> bool:
    """Recognize city intent even when profile reconstruction loses one enum."""
    if v12._is_city_profile(result):
        return True
    p = _profile_dict(result)
    if str(p.get("primary_job") or "").lower() == "city_runabout":
        return True
    blob = " ".join(
        str(p.get(k) or "")
        for k in ("primary_job", "secondary_job", "usage", "intent_segment", "priority", "secondary")
    )
    if _CITY_WORDS_RE.search(blob):
        return True
    bodies = " ".join(str(x) for k in ("prefer_body", "require_body") for x in (p.get(k) or []))
    # Hatch/sedan preference alone is not enough if this is explicitly a work/pickup mission.
    work_blob = " ".join(str(p.get(k) or "") for k in ("primary_job", "intent_segment", "usage"))
    return bool(re.search(r"\b(?:hatch|hatchback|sedan|compact)\b", bodies, re.I) and not re.search(r"\b(?:work|pickup|carga|delivery)\b", work_blob, re.I))


def _hard_incompatible(card: dict) -> bool:
    blob = " ".join(str(card.get(k) or "") for k in ("make", "model"))
    return bool(_HARD_PICKUP_RE.search(blob))


def _enforce_city_truth(result: Any) -> Any:
    if not isinstance(result, dict) or result.get("phase") != "recommendation" or not _city_intent(result):
        return result
    strong = [c for c in list(result.get("recommendations") or []) if isinstance(c, dict) and not _hard_incompatible(c)]
    explore = [c for c in list(result.get("explore") or []) if isinstance(c, dict) and not _hard_incompatible(c)]
    result["recommendations"] = strong[: v12.v11.MAX_STRONG]
    result["explore"] = explore[: v12.v11.MAX_EXPLORE]
    result["favorite"] = result["recommendations"][0] if result["recommendations"] else None
    result["recommendation_count"] = len(result["recommendations"])
    result["explore_count"] = len(result["explore"])
    result["quality_candidate_count"] = len(result["recommendations"]) + len(result["explore"])
    # pool_size means evaluated market breadth, not options Carly is willing to show.
    result["more_options_available"] = False
    result["more_options_count"] = 0
    result["option_count_semantics"] = "pool_evaluated_vs_quality_candidates"
    decision = result.get("decision")
    if isinstance(decision, dict):
        decision["recommendations"] = list(result["recommendations"])
        decision["explore"] = list(result["explore"])
        decision["favorite"] = result["favorite"]
        decision["quality_candidate_count"] = result["quality_candidate_count"]
    return result


def _remove_em_dash(text: str) -> str:
    # Carly uses compact punctuation. A semicolon reads better than a long dash in chat.
    return str(text or "").replace(" — ", "; ").replace("—", "-")


def _bold_first_sentence(reply: str) -> str:
    """Cheap hierarchy for ordinary Carly replies using the frontend markdown renderer."""
    text = _remove_em_dash(reply)
    if not text.strip() or "**" in text:
        return text
    # Do not turn a single bare question into a heavy block. Prefer a short lead sentence.
    m = re.match(r"^(\s*)([^\n.!?]{2,145}[.!?])(?=\s|$)", text)
    if not m:
        return text
    lead = m.group(2).strip()
    if lead.startswith("¿") or lead.startswith("?"):
        return text
    return f"{m.group(1)}**{lead}**{text[m.end():]}"


def _presentation(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    reply = result.get("reply")
    if isinstance(reply, str) and reply:
        result["reply"] = _bold_first_sentence(reply)
        result["render_hint"] = result.get("render_hint") or "compact_hierarchy_markdown"
        result["presentation_policy"] = {
            "bold_lead": True,
            "scan_friendly": True,
            "em_dash": False,
        }
    return result


def _patch_v13_route() -> None:
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != "/carly/chat":
            continue
        endpoint = getattr(route, "endpoint", None)
        dependant = getattr(route, "dependant", None)
        if endpoint is None or dependant is None:
            continue
        prior = endpoint

        def v13_endpoint(*args: Any, __prior=prior, **kwargs: Any):
            result = __prior(*args, **kwargs)
            result = _enforce_city_truth(result)
            return _presentation(result)

        route.endpoint = v13_endpoint
        dependant.call = v13_endpoint
        break


_patch_v13_route()
