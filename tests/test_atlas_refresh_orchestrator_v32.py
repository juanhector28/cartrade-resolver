from datetime import datetime, timezone
from pathlib import Path

from app.atlas_refresh_orchestrator import _observed_urls, source_is_due


def test_source_is_due_uses_oldest_exact_row_clock():
    now = datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)
    stale = {
        "oldest_last_seen_at": "2026-09-17T15:59:59+00:00",
        "newest_last_seen_at": "2026-09-19T15:59:00+00:00",
    }
    assert source_is_due(stale, 86400, now=now) is True


def test_source_is_not_due_when_entire_source_is_fresh():
    now = datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)
    fresh = {
        "oldest_last_seen_at": "2026-09-19T10:00:00+00:00",
        "newest_last_seen_at": "2026-09-19T15:59:00+00:00",
    }
    assert source_is_due(fresh, 86400, now=now) is False


def test_observed_urls_prefers_full_runner_evidence():
    result = {
        "observed_urls": ["https://example.com/1", "https://example.com/2"],
        "sample": [{"url": "https://example.com/1"}],
    }
    assert _observed_urls(result) == {
        "https://example.com/1",
        "https://example.com/2",
    }


def test_runner_returns_observed_urls():
    source = Path("app/atlas_manifest_runner.py").read_text(encoding="utf-8")
    assert '"observed_urls": [' in source
    assert "for item in valid" in source


def test_v32_is_wired_after_v31():
    docker = Path("Dockerfile").read_text(encoding="utf-8")
    assert "resolver_patch_atlas_v32.py" in docker
    assert docker.index("resolver_patch_atlas_v31.py") < docker.index("resolver_patch_atlas_v32.py")

    patch = Path("resolver_patch_atlas_v32.py").read_text(encoding="utf-8")
    assert "ATLAS_REFRESH_ORCHESTRATOR_V32" in patch
    assert "_install_atlas_refresh_orchestrator" in patch


def test_scheduler_keeps_strong_task_reference():
    source = Path("app/atlas_refresh_orchestrator.py").read_text(encoding="utf-8")
    assert "app.state._atlas_refresh_scheduler_task_v32 = task" in source
    assert "ATLAS_REFRESH_SCHEDULER_STARTED" in source
    assert "ATLAS_REFRESH_SCHEDULER_POLL" in source


def test_custom_lifespan_bridges_registered_startup_handlers():
    main_source = Path("app/main.py").read_text(encoding="utf-8")
    assert "await _run_registered_lifecycle_handlers(app.router.on_startup)" in main_source
    assert "await _run_registered_lifecycle_handlers(app.router.on_shutdown)" in main_source
    assert "_legacy_startup_handlers_ran" in main_source


def test_failed_refresh_is_retryable_and_invalid_shadows_are_quarantined():
    source = Path("app/atlas_refresh_orchestrator.py").read_text(encoding="utf-8")
    assert 'retry_failed = str(source.get("last_refresh_status") or "").strip().lower() == "failed"' in source
    assert "due = retry_failed or source_is_due(" in source
    assert "_quarantine_invalid_shadow_candidates(" in source
    assert '"reason": "invalid_listing_current_refresh"' in source
    assert '"quarantined_invalid": quarantined["count"]' in source


def test_registry_outcome_preserves_existing_lifecycle_fields():
    source = Path("app/atlas_refresh_orchestrator.py").read_text(encoding="utf-8")
    assert 'current = resolve_source(supabase, str(source.get("source_id") or ""))' in source
