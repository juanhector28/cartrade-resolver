from datetime import datetime, timezone
from pathlib import Path

from app.atlas_freshness_api import effective_search_country, freshness_policy


def test_explicit_country_is_normalized():
    assert effective_search_country("GT", None) == "gt"
    assert effective_search_country(" gt ", None) == "gt"


def test_source_scoped_probe_infers_country():
    assert effective_search_country(None, "gt-agautoventas-com") == "gt"
    assert effective_search_country("", "sv-example-com") == "sv"
    assert effective_search_country(None, "not-a-market") is None


def test_gt_source_only_probe_gets_demo_freeze(monkeypatch):
    monkeypatch.setenv("ATLAS_GT_DEMO_FREEZE_CUTOFF", "2026-09-12T18:00:00Z")
    monkeypatch.setenv("ATLAS_GT_DEMO_FREEZE_UNTIL", "2026-09-16T23:59:59Z")
    country = effective_search_country(None, "gt-autogogt-com")
    policy = freshness_policy(country, now=datetime(2026, 9, 15, 6, 0, tzinfo=timezone.utc))
    assert policy["mode"] == "gt_demo_freeze_pin"
    assert policy["cutoff"] == "2026-09-12T18:00:00+00:00"


def test_v31_patch_binds_search_freshness_to_effective_country():
    patch = Path("resolver_patch_atlas_v31.py").read_text(encoding="utf-8")
    assert "_atlas_freshness_cutoff_iso(_atlas_effective_search_country(" in patch
    assert 'q = q.eq("country", _atlas_effective_search_country(' in patch
