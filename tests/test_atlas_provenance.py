from app.atlas_provenance import carly_provenance


def test_atlas_row_exposes_factory_provenance_without_raw_payload_contract():
    row = {
        "source": "atlas:fixture.local",
        "raw_payload": {"atlas": {"source_id": "golden-dom", "manifest_version": 7}},
    }
    assert carly_provenance(row) == {"source_id": "golden-dom", "manifest_version": 7}


def test_manual_row_falls_back_to_source_name():
    row = {"source": "manual-source", "raw_payload": {}}
    assert carly_provenance(row) == {"source_id": "manual-source", "manifest_version": None}
