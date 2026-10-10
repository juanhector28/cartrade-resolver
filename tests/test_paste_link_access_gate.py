import json
from pathlib import Path
from scripts.paste_link_access_gate import validate


def test_current_pilot_sources_are_not_authorized():
    ok, issues = validate(
        Path("ops/paste_link_smoke_cases.json"),
        Path("ops/paste_link_access_review.json"),
    )
    assert not ok
    assert len(issues) == 3


def test_only_complete_documented_grant_is_accepted(tmp_path):
    cases = [{"source_id":"sv-test","url":"https://dealers.example/auto/123"}]
    grants = {"sources":[{"source_id":"sv-test","domain":"dealers.example","authorized":True,
                          "status":"authorized","agreement_reference":"WRITTEN-001",
                          "price_collection_permitted":True}]}
    c, r = tmp_path/"cases.json", tmp_path/"register.json"
    c.write_text(json.dumps(cases))
    r.write_text(json.dumps(grants))
    assert validate(c,r) == (True,[])
    grants["sources"][0]["agreement_reference"] = ""
    r.write_text(json.dumps(grants))
    assert not validate(c,r)[0]


def test_mismatched_domain_is_rejected(tmp_path):
    c, r = tmp_path/"cases.json", tmp_path/"register.json"
    c.write_text(json.dumps([{"source_id":"sv-test","url":"https://wrong.example/auto/1"}]))
    r.write_text(json.dumps({"sources":[{"source_id":"sv-test","domain":"dealers.example",
       "authorized":True,"status":"authorized","agreement_reference":"WRITTEN-001",
       "price_collection_permitted":True}]}))
    assert not validate(c,r)[0]
