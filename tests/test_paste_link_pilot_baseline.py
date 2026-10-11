"""Versioned pilot source freeze: cannot silently promote experimental candidates."""
import json
from pathlib import Path
from app.paste_link_readiness import get_readiness
from app.paste_link_source_registry import SOURCES, source_for_url

BASELINE=Path("ops/paste_link_sv_pilot_baseline.json")
QA=Path("ops/paste_link_sv_qa_3_per_site.json")
QUEUE=Path("ops/paste_link_sv_next_wave.json")

def test_frozen_pilot_set_corresponds_to_actual_qa():
    baseline=json.loads(BASELINE.read_text())
    matrix=json.loads(QA.read_text())
    ready=get_readiness()
    assert baseline["production_allowed"] is False
    assert len(baseline["baseline_sources"])==11
    assert {x["domain"] for x in baseline["baseline_sources"]} == {
        x["domain"] for x in matrix["domains"]
    }
    assert ready["pilot_candidates"]==11
    assert ready["core_field_samples_verified"]==33
    assert ready["production_deploy_permitted"] is False
    per_domain={x["domain"]:x for x in matrix["domains"]}
    for entry in baseline["baseline_sources"]:
        d=entry["domain"]
        actual=per_domain[d]["cases"]
        assert entry["listing_count"] == 3
        assert entry["urls"] == [c["url"] for c in actual]
        assert entry["evidence_types"] == [c["status"] for c in actual]
        assert SOURCES[d]["stage"] == "browser_sample_verified"
        assert all(source_for_url(url) and source_for_url(url)[0] == d for url in entry["urls"])

def test_next_wave_does_not_unlock_sources_or_prod():
    baseline=json.loads(BASELINE.read_text())
    queue=json.loads(QUEUE.read_text())
    ready=get_readiness()
    baseline_hosts={s["domain"] for s in baseline["baseline_sources"]}
    queue_hosts={s["domain"].removeprefix("www.") for s in queue["priorities"]}
    assert not baseline_hosts.intersection(queue_hosts)
    assert queue["priorities"] and len(queue["priorities"])>=5
    assert not ready["production_approved_domains"]
    assert all(not x["production_approved"] for x in queue["priorities"])
    assert all("next_acceptance" in x for x in queue["priorities"])
    assert all(
        (SOURCES.get(x["domain"]) or {}).get("stage") != "browser_sample_verified"
        for x in queue["priorities"]
    )
