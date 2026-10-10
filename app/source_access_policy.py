"""Fail-closed authorization gate for scheduled marketplace ingestion.

This gate is separate from parsing. A technically accessible page is not
automatically an authorized collection source.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SOURCE_POLICIES = {
    "encuentra24": "written_authorization_required",
}


def may_ingest(source: str, grant: dict[str, Any] | None, *, at: datetime | None = None) -> tuple[bool, str]:
    """Require explicit, valid authorization for sources with restrictive terms.

    Unknown sources fail closed pending a source-level policy review.
    """
    policy = SOURCE_POLICIES.get((source or "").strip().lower())
    if policy is None:
        return False, "source_policy_not_reviewed"
    if policy == "written_authorization_required":
        if not isinstance(grant, dict):
            return False, "written_authorization_missing"
        if grant.get("status") != "approved" or grant.get("permission") != "commercial_inventory_ingestion":
            return False, "permission_not_approved"
        if not str(grant.get("agreement_reference") or "").strip():
            return False, "agreement_reference_missing"
        if not grant.get("redisplay_permitted") or not grant.get("price_collection_permitted"):
            return False, "field_rights_missing"
        expires = grant.get("expires_at")
        if not isinstance(expires, str):
            return False, "expiry_missing"
        try:
            expiry = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        except ValueError:
            return False, "expiry_invalid"
        if expiry.tzinfo is None:
            return False, "expiry_invalid"
        at = at or datetime.now(timezone.utc)
        if expiry <= at:
            return False, "authorization_expired"
        return True, "authorized"
    return False, "unsupported_policy"
