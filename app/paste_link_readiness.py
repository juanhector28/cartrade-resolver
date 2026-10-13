"""Offline evidence ledger for Carly Paste Link staging.

This module reads committed QA receipts and manual release controls only.
It NEVER fetches third-party sites or authorizes deploying to production.
"""
from __future__ import annotations

import json
from pathlib import Path

from .paste_link_source_registry import SOURCES, source_for_url, enabled_now

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / "ops" / "paste_link_sv_qa_3_per_site.json"
CONTROLS = ROOT / "ops" / "paste_link_sv_release_controls.json"
NEXT_WAVE = ROOT / "ops" / "paste_link_sv_next_wave.json"
SUCCESS_STATES = frozenset({"api_passed", "browser_passed"})


def _read(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def get_readiness() -> dict:
    """Return derived, conservative readiness without relying on stale totals."""
    matrix = _read(MATRIX)
    controls = _read(CONTROLS)
    upcoming = _read(NEXT_WAVE)
    minimum = controls["pilot_requirements"]["min_distinct_listing_samples_per_domain"]
    min_browser = controls["pilot_requirements"]["min_browser_loaded_photo_samples_per_domain"]
    rows = []
    all_urls = set()
    issues = []

    for source in matrix["domains"]:
        domain = source["domain"]
        entry = SOURCES.get(domain)
        examples = source["cases"]
        unique_urls = {c["url"] for c in examples}
        passed = sum(c["status"] in SUCCESS_STATES and bool(c.get("evidence")) for c in examples)
        browser = sum(c["status"] == "browser_passed" and bool(c.get("evidence")) for c in examples)
        valid_routes = all(
            (match := source_for_url(c["url"])) is not None and match[0] == domain
            for c in examples
        )
        duplicates = all_urls.intersection(unique_urls)
        if duplicates:
            issues.append("duplicate cross-domain URL: " + domain)
        all_urls.update(unique_urls)
        pilot = bool(
            entry and enabled_now(domain) and entry["stage"] == "browser_sample_verified"
            and len(unique_urls) == len(examples)
            and len(unique_urls) >= minimum and passed >= minimum
            and browser >= min_browser and valid_routes
        )
        if not pilot:
            issues.append("pilot evidence incomplete: " + domain)
        rows.append({
            "domain": domain,
            "name": entry["name"] if entry else domain,
            "state": "pilot_candidate" if pilot else "needs_more_qa",
            "distinct_vehicle_urls": len(unique_urls),
            "core_field_samples_passed": passed,
            "photos_loaded_in_browser_samples": browser,
            "full_photo_gallery_coverage": False,
            "pricing_revalidated_on_each_request": False,
            "commercial_use_approved": False,
            "production_enabled": False,
        })

    control_status = {
        key: {
            "approved": value.get("approved") is True and bool(value.get("evidence")),
            "owner": value.get("owner"),
            "note": value.get("note"),
        }
        for key, value in controls["release_gates"].items()
    }
    manual_clear = all(x["approved"] for x in control_status.values())
    enabled_sources = [k for k in SOURCES if enabled_now(k)]
    blocked_domains = [
        {
            "domain": key, "name": v["name"], "stage": v["stage"],
            "enabled_for_manual_trial": enabled_now(key),
        }
        for key, v in SOURCES.items()
        if v["stage"] not in {"browser_sample_verified"}
    ]
    candidate_count = sum(row["state"] == "pilot_candidate" for row in rows)
    # The global approval is not inferred from green QA tests.
    deployment_permitted = bool(
        controls.get("production_deploy_permitted") is True
        and manual_clear and not issues
        and controls.get("approved_production_domains")
        and set(controls["approved_production_domains"]).issubset({
            r["domain"] for r in rows if r["state"] == "pilot_candidate"
        })
    )
    return {
        "environment": "staging",
        "source_of_truth": "committed QA evidence and manual release controls",
        "evidence_as_of": matrix.get("updated_at", matrix.get("as_of")),
        "sample_target_per_domain": minimum,
        "pilot_candidates": candidate_count,
        "tested_domains": len(rows),
        "core_field_samples_verified": sum(r["core_field_samples_passed"] for r in rows),
        "photo_browser_samples": sum(r["photos_loaded_in_browser_samples"] for r in rows),
        "enabled_trial_domains": len(enabled_sources),
        "other_registered_domains": blocked_domains,
        "next_wave": [
            {
                "rank": item["rank"], "source": item["source"],
                "domain": item["domain"], "state": item["status"],
                "blocker": item["blocker"], "acceptance": item["next_acceptance"],
                "production_approved": False,
            }
            for item in upcoming["priorities"]
        ],
        "production_approved_domains": list(controls.get("approved_production_domains", [])),
        "production_deploy_permitted": deployment_permitted,
        "production_release_gates": control_status,
        "evidence_issues": issues,
        "sources": rows,
        "limitations": (
            "Not live source health or blanket source certification. "
            "Photo browser samples do not cover all listings. "
            "Commercial content permissions and production checks remain separate."
        ),
    }
