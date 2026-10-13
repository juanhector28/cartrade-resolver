"""Read-only URL recognition for the original 56 Atlas El Salvador sources.

Recognizing a domain does NOT authorize fetching it, certify an inventory or
record a buyer request. This module makes ZERO network requests and ZERO writes.
"""
from __future__ import annotations

import ipaddress
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

REGISTRY = Path(__file__).resolve().parent.parent / "ops" / "paste_link_sv_56_sources.json"
STATUS_VERIFIED = "sample_verified"
STATUS_TRIAL = "trial_unverified"


def _canonical_host(hostname: str) -> str:
    hostname = hostname.lower().rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def _safe_host(raw: str) -> str | None:
    """Allow only ordinary HTTPS hostnames, not IPs, credentials or custom ports."""
    if not isinstance(raw, str) or not 12 <= len(raw) <= 2048:
        return None
    if any(ord(c) <= 32 or ord(c) == 127 for c in raw):
        return None
    try:
        parsed = urlsplit(raw)
        if (parsed.scheme != "https" or not parsed.netloc
                or parsed.username is not None or parsed.password is not None
                or parsed.port is not None):
            return None
        host = _canonical_host(parsed.hostname or "")
        if (not host or len(host) > 253 or "." not in host
                or host in {"localhost", "local", "internal"}
                or host.endswith((".localhost", ".local", ".internal"))):
            return None
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return None
        return host
    except (ValueError, TypeError):
        return None


@lru_cache(maxsize=1)
def _registry() -> tuple[dict, dict[str, dict]]:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = data["sources"]
    if (data.get("source_count") != 56 or len(rows) != 56
            or len({row["source_id"] for row in rows}) != 56):
        raise ValueError("atlas_sv56_registry_invalid")
    mapping = {}
    for row in rows:
        host = _safe_host(row["homepage"])
        if not host or host in mapping:
            raise ValueError("atlas_sv56_host_invalid")
        mapping[host] = row
    return data, mapping


def reference_for_url(url: str) -> dict | None:
    """Identify known source only. Do not fetch, persist or even emit the URL."""
    hostname = _safe_host(url)
    if not hostname:
        return None
    _data, sources = _registry()
    row = sources.get(hostname)
    if row is None:
        # Anuto was discovered outside the original 56-source census.
        if hostname == "sv.anuto.app":
            return {
                "source_id": "sv-anuto-extra",
                "source_name": "Anuto El Salvador",
                "link_status": STATUS_VERIFIED,
                "within_original_56": False,
                "status": "recognized_unstored",
                "saved": False,
                "fetched": False,
                "vehicle_fields_verified": False,
            }
        return None
    return {
        "source_id": row["source_id"],
        "source_name": row["name"],
        "link_status": row["link_status"],
        "within_original_56": True,
        "status": "recognized_unstored",
        "saved": False,
        "fetched": False,
        "vehicle_fields_verified": False,
    }


def reference_coverage() -> dict:
    data, _by_host = _registry()
    statuses = {}
    for item in data["sources"]:
        state = item["link_status"]
        statuses[state] = statuses.get(state, 0) + 1
    return {
        "environment": "staging",
        "registered_sources": 56,
        "recognized_reference_domains": 56,
        "additional_sample_verified_domains": 1,
        "sample_verified_of_56": statuses.get(STATUS_VERIFIED, 0),
        "trial_unverified_of_56": statuses.get(STATUS_TRIAL, 0),
        "other_not_automatically_verified": (
            56 - statuses.get(STATUS_VERIFIED, 0)
            - statuses.get(STATUS_TRIAL, 0)
        ),
        "by_status": statuses,
        "network_fetch": False,
        "intake_enabled": False,
        "saved": False,
        "production_deploy_permitted": False,
        "sources": [
            {
                "source_id": x["source_id"],
                "name": x["name"],
                "kind": x["kind"],
                "link_status": x["link_status"],
            }
            for x in data["sources"]
        ],
    }
