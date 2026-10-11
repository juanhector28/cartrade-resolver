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
def test_all_33_cases_have_real_source_evidence_without_confusing_photo_tiers():
    d=json.loads(MATRIX.read_text())
    assert d["result"]["title_asking_price_model_year_photo_url_fields_passed"]==33
    assert d["result"]["domains"]==11
    cases=[x for group in d["domains"] for x in group["cases"]]
    assert len(cases)==33
    assert all(x["status"] in ("browser_passed","api_passed") for x in cases)
    assert all(x.get("evidence","").startswith("https://github.com/") for x in cases)
    assert any(x["status"]=="api_passed" for x in cases)
    assert any(x["status"]=="browser_passed" for x in cases)
    # API photo URL != browser image actually loaded. The tiers stay separate.
    assert d["result"]["each_photo_browser_rendered"] is False
