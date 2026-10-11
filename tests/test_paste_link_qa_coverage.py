"""QA coverage guard: eleven domains with three distinct real listing URLs."""
import json
from pathlib import Path
from app.paste_link_source_registry import source_for_url
MATRIX=Path("ops/paste_link_sv_qa_3_per_site.json")
def test_eleventh_sources_three_unique_vehicle_urls_each():
    d=json.loads(MATRIX.read_text())
    assert d["target_distinct_listings_per_domain"]==3
    assert len(d["domains"])==11
    assert len({row["domain"] for row in d["domains"]})==11
    for row in d["domains"]:
        assert len(row["cases"])==3,row["domain"]
        urls=[x["url"] for x in row["cases"]]
        assert len(set(urls))==3,row["domain"]
        assert all(source_for_url(url) and source_for_url(url)[0]==row["domain"] for url in urls)
        assert all(1950 <= x["expected_year"] <= 2035 for x in row["cases"])
        assert all(500 <= x["atlas_reference_price"] <= 200000 for x in row["cases"])
def test_missing_checks_not_reported_as_browser_success():
    d=json.loads(MATRIX.read_text())
    for row in d["domains"]:
        for example in row["cases"]:
            if example["status"]!="browser_passed":
                assert example["status"] in {
                    "api_passed", "source_parser_passed",
                    "api_partial_year_fixed_pending_retest"
                }
                assert example["status"]!="browser_passed"
    assert any(
        x["status"]=="source_parser_passed"
        for row in d["domains"] for x in row["cases"]
    )
