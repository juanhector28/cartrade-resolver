from app.atlas_listing_validity import is_valid_listing, listing_validity
from app.atlas_publish_api import _publish_rollback_quarantined


def _row(make: str):
    return {
        "url": "https://example.com/vehicle/1",
        "make": make,
        "model": "RANGER",
        "year": 2024,
        "price_usd": 15000,
    }


def test_publisher_contract_rejects_navigation_heading_as_make():
    assert is_valid_listing(_row("Vehículos Relacionados")) is False


def test_publisher_contract_rejects_faq_heading_as_make():
    assert is_valid_listing(_row("❓ Preguntas Frecuentes")) is False


def test_publisher_contract_accepts_known_vehicle_make():
    assert is_valid_listing(_row("Ford")) is True


def test_bad_historical_rows_reduce_publish_coverage():
    rows = [_row("Ford") for _ in range(8)] + [_row("Vehículos Relacionados") for _ in range(3)]
    out = listing_validity(rows, current_year=2026)
    assert out["valid_count"] == 8
    assert out["invalid_count"] == 3
    assert out["passes_threshold"] is False


def test_publish_rollback_row_is_quarantined_from_future_candidate_cohort():
    row = _row("Vehículos Relacionados")
    row["raw_payload"] = {
        "atlas": {
            "source_id": "gt-movilauto-com",
            "manifest_version": 3,
            "publish_rollback": {
                "reason": "invalid_make_inference_contamination_v28_guard"
            },
        }
    }
    assert _publish_rollback_quarantined(row) is True


def test_current_valid_row_without_rollback_remains_publish_candidate():
    row = _row("Mazda")
    row["raw_payload"] = {
        "atlas": {
            "source_id": "gt-movilauto-com",
            "manifest_version": 3,
        }
    }
    assert _publish_rollback_quarantined(row) is False
