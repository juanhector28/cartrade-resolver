from datetime import datetime, timezone
from app.carly_inventory_policy import annotate


def test_history_is_explicit_without_rewriting_observation_date():
    observed = "2026-06-04T00:00:00Z"
    data = {"reply": "Estas son las opciones.", "recommendations": [{"last_seen_at": observed}]}
    result = annotate(data, now=datetime(2026, 10, 4, tzinfo=timezone.utc))
    assert result["recommendations"][0]["last_seen_at"] == observed
    assert result["recommendations"][0]["requires_availability_confirmation"] is True
    assert "históricos" in result["reply"]
    assert result["inventory_policy"]["max_age_seconds"] is None
    assert result["inventory_policy"]["source_allowlist"] is None


def test_recent_observation_does_not_get_a_historical_label():
    data = {"reply": "Opciones", "recommendations": [{"last_seen_at": "2026-10-04T00:00:00Z"}]}
    result = annotate(data, now=datetime(2026, 10, 4, 1, tzinfo=timezone.utc))
    assert result["recommendations"][0]["requires_availability_confirmation"] is False
    assert result["reply"] == "Opciones"
