from __future__ import annotations

from typing import Any


def carly_provenance(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw_payload") if isinstance(row, dict) else None
    atlas = raw.get("atlas") if isinstance(raw, dict) else None
    atlas = atlas if isinstance(atlas, dict) else {}
    source_id = atlas.get("source_id") or row.get("source")
    manifest_version = atlas.get("manifest_version")
    return {
        "source_id": str(source_id) if source_id not in (None, "") else None,
        "manifest_version": manifest_version,
    }
