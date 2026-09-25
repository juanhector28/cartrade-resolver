from __future__ import annotations

from datetime import datetime, timezone

from app.atlas_freshness_api import freshness_policy


# Diagnostic snapshot of the five GT demo-certified sources on 2026-09-14.
# 22 + 23 + 36 + 20 + 19 = exactly 120 staging/indexed/addressable rows.
_CERTIFIED_GT = [
    (22, "2026-09-12T18:21:41.321437+00:00", "2026-09-12T18:21:45.385781+00:00"),
    (23, "2026-09-12T18:21:47.277916+00:00", "2026-09-12T18:21:52.166538+00:00"),
    (36, "2026-09-12T18:21:55.019525+00:00", "2026-09-12T18:22:21.210454+00:00"),
    (20, "2026-09-12T18:21:36.951924+00:00", "2026-09-12T18:21:39.671855+00:00"),
    (19, "2026-09-12T18:51:59.031047+00:00", "2026-09-12T18:52:05.282982+00:00"),
]


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def test_gt_freeze_pin_keeps_all_120_fresh_through_tuesday(monkeypatch):
    monkeypatch.setenv("ATLAS_SEARCH_FRESHNESS_MAX_AGE_SECONDS", "86400")
    monkeypatch.setenv("ATLAS_GT_DEMO_FREEZE_CUTOFF", "2026-09-12T18:00:00+00:00")
    monkeypatch.setenv("ATLAS_GT_DEMO_FREEZE_UNTIL", "2026-09-16T23:59:59+00:00")

    # Deliberately test the end of Tuesday UTC, not merely the current instant.
    tuesday = datetime(2026, 9, 15, 23, 59, 59, tzinfo=timezone.utc)
    policy = freshness_policy("gt", now=tuesday)
    cutoff = _dt(policy["cutoff"])

    assert policy["mode"] == "gt_demo_freeze_pin"
    assert sum(n for n, _, _ in _CERTIFIED_GT) == 120
    assert all(_dt(min_seen) >= cutoff for _, min_seen, _ in _CERTIFIED_GT)
    assert all(_dt(max_seen) >= cutoff for _, _, max_seen in _CERTIFIED_GT)


def test_freeze_pin_is_gt_only_and_hard_expires(monkeypatch):
    monkeypatch.setenv("ATLAS_SEARCH_FRESHNESS_MAX_AGE_SECONDS", "86400")
    monkeypatch.setenv("ATLAS_GT_DEMO_FREEZE_CUTOFF", "2026-09-12T18:00:00+00:00")
    monkeypatch.setenv("ATLAS_GT_DEMO_FREEZE_UNTIL", "2026-09-16T23:59:59+00:00")

    during = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    emergency = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    after = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

    assert freshness_policy("gt", now=during)["mode"] == "gt_demo_freeze_pin"
    assert freshness_policy("sv", now=during)["mode"] == "rolling"

    emergency_policy = freshness_policy("gt", now=emergency)
    assert emergency_policy["mode"] == "gt_demo_emergency_extension"
    assert emergency_policy["cutoff"] == "2026-09-12T18:00:00+00:00"
    assert emergency_policy["freeze_until"] == "2026-09-30T23:59:59+00:00"

    assert freshness_policy("gt", now=after)["mode"] == "rolling"
