"""Candidate queue cannot silently enable or certify blocked sources."""
import json
from pathlib import Path
from urllib.parse import urlparse

from app.paste_link_source_registry import SOURCES, source_for_url

QUEUE = Path("ops/paste_link_sv_next_wave.json")

def test_next_wave_has_ranked_evidence_and_acceptance_for_each_source():
    queue=json.loads(QUEUE.read_text())
    items=queue["priorities"]
    assert len(items)>=9
    assert [x["rank"] for x in items]==list(range(1,len(items)+1))
    assert len({x["domain"] for x in items})==len(items)
    for item in items:
        assert item["next_acceptance"] and len(item["next_acceptance"])>25
        assert item["blocker"] and len(item["blocker"])>25
        assert item["production_approved"] is False
        assert item["sample_url"].startswith("https://")
        host=(urlparse(item["sample_url"]).hostname or "").removeprefix("www.")
        assert host==item["domain"].removeprefix("www."),item["source"]

def test_next_wave_never_accidentally_promoted_from_reference_urls():
    queue=json.loads(QUEUE.read_text())
    for item in queue["priorities"]:
        url=item["sample_url"]
        registry=SOURCES.get(item["domain"])
        if registry:
            assert registry["stage"]!="browser_sample_verified"
            assert not registry["enabled"] or registry["stage"] in {
                "javascript_required","access_review",
            }
        if not registry or not registry["enabled"]:
            assert source_for_url(url) is None
    assert SOURCES["autosale.com.sv"]["enabled"] is False
    assert SOURCES["credipro.com.sv"]["enabled"] is False
