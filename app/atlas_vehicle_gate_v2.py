from __future__ import annotations

import re
from typing import Any


MOTORCYCLE_ONLY_MAKES = {
    "yamaha", "kawasaki", "ducati", "harley-davidson", "harley davidson",
    "ktm", "husqvarna", "vespa", "bajaj", "tvs", "hero", "royal enfield",
    "cfmoto", "cf moto", "can-am", "can am", "serpento", "benelli",
    "aprilia", "moto guzzi", "triumph motorcycles", "victory motorcycles",
}

EXPLICIT_NON_CAR_HINTS = (
    "/moto-", "/motos/", " motocic", "moto ", "moto-", " atv", "atv ",
    "cuatri", "scooter", "quadric", "motocross", "motocicleta", "moped",
    "side-by-side", "side by side", "utv ", " utv",
)

HONDA_MOTO_MODEL_PREFIXES = (
    "elite", "pcx", "navi", "dio", "wave", "cbr", "crf", "xr", "xre",
    "cbf", "cb ", "cb1", "cb2", "cb3", "cb4", "cb5", "cb6", "cb7", "cb8",
    "adv", "rebel", "shadow", "gold wing", "goldwing", "africa twin",
)

SUZUKI_MOTO_MODEL_PREFIXES = (
    "gsx", "gixxer", "v-strom", "vstrom", "burgman", "hayabusa", "dr-z",
    "drz", "gn ", "en ", "ax ", "gixxer",
)

BMW_MOTO_MODEL_PREFIXES = (
    "r 1", "r1", "f 7", "f7", "f 8", "f8", "f 9", "f9", "s 1", "s1",
    "g 3", "g3", "k 1", "k1", "r nine", "r-nine",
)

_DISPLACEMENT_RE = re.compile(
    r"\b(?:[4-9]\d|[1-9]\d{2}|1\d{3})\s*(?:cc|c\.c\.|cil(?:indrada)?s?)\b",
    re.I,
)


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("name", "value", "title", "description"):
            if value.get(key) not in (None, "", []):
                return _scalar(value.get(key))
        return ""
    if isinstance(value, list):
        return " ".join(x for x in (_scalar(v) for v in value) if x)
    return str(value).strip()


def classify_non_car(item: dict[str, Any]) -> tuple[bool, str | None]:
    make = _scalar(item.get("make")).lower()
    model = _scalar(item.get("model")).lower()
    title = _scalar(item.get("title")).lower()
    url = _scalar(item.get("url")).lower()

    evidence = " ".join((url, title, make, model)).replace("autos-motos", "")

    if any(h in evidence for h in EXPLICIT_NON_CAR_HINTS):
        return True, "explicit_two_wheeler_or_atv_evidence"

    if make in MOTORCYCLE_ONLY_MAKES:
        return True, "motorcycle_only_make"

    if make == "honda" and model.startswith(HONDA_MOTO_MODEL_PREFIXES):
        return True, "honda_motorcycle_model_family"

    if make == "suzuki" and model.startswith(SUZUKI_MOTO_MODEL_PREFIXES):
        return True, "suzuki_motorcycle_model_family"

    if make == "bmw" and model.startswith(BMW_MOTO_MODEL_PREFIXES):
        return True, "bmw_motorcycle_model_family"

    # Engine-displacement language in the title/model is strong evidence for a
    # motorcycle/ATV listing. Avoid scanning arbitrary page text so car engine
    # sizes such as 2.0L are not confused with this rule.
    if _DISPLACEMENT_RE.search(" ".join((title, model))):
        return True, "motorcycle_displacement_pattern"

    return False, None


def install(ns: dict[str, Any]) -> None:
    if ns.get("_ATLAS_VEHICLE_GATE_V2_INSTALLED"):
        return
    ns["_ATLAS_VEHICLE_GATE_V2_INSTALLED"] = True

    original_extract = ns["extract_listing"]
    original_quality = ns.get("_atlas_activation_quality")

    def extract_with_vehicle_gate(manifest: dict, url: str, html: str) -> dict[str, Any]:
        item = original_extract(manifest, url, html)
        rejected, reason = classify_non_car(item)
        if rejected:
            item["_semantic_reject_reason"] = reason or "non_car_listing_v2"
            item["_required_ok"] = False
            item["_vehicle_gate_v2"] = "rejected"
        else:
            item["_vehicle_gate_v2"] = "accepted"
        return item

    ns["extract_listing"] = extract_with_vehicle_gate

    if callable(original_quality):
        def quality_with_vehicle_gate(sample):
            out = dict(original_quality(sample) or {})
            rows = list(sample or [])[:5]
            rejected = 0
            reasons: list[str] = []
            for item in rows:
                bad, reason = classify_non_car(item)
                if bad:
                    rejected += 1
                    if reason and reason not in reasons:
                        reasons.append(reason)
            out["vehicle_gate_v2"] = True
            out["non_car_v2_count"] = rejected
            out["non_car_v2_reasons"] = reasons
            if rejected:
                issues = list(out.get("issues") or [])
                if "non_car_inventory_detected_v2" not in issues:
                    issues.append("non_car_inventory_detected_v2")
                out["issues"] = issues
                out["eligible"] = False
            return out

        ns["_atlas_activation_quality"] = quality_with_vehicle_gate
