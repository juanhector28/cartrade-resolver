"""Capture social references in Atlas; never fetch social pages or publish cars."""
from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from .social_metadata import recover_metadata

HOSTS = {
    "facebook": {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.com", "www.fb.com", "fb.watch"},
    "instagram": {"instagram.com", "www.instagram.com"},
    "tiktok": {"tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"},
}


def social_platform(url: str) -> str | None:
    try:
        p = urlparse(url)
        if p.scheme != "https" or p.username or p.password or p.port:
            return None
        return next((name for name, hosts in HOSTS.items() if p.hostname in hosts), None)
    except (ValueError, TypeError):
        return None


async def capture_reference(url: str, country: str | None) -> dict:
    platform = social_platform(url)
    if not platform:
        raise HTTPException(400, "Enlace social no válido.")
    country = (country or "").upper().strip()
    if country not in {"SV", "GT"}:
        raise HTTPException(422, "Selecciona El Salvador o Guatemala para guardar esta publicación.")
    base = os.getenv("ATLAS_SOCIAL_URL", "").rstrip("/")
    token = os.getenv("ATLAS_SOCIAL_TOKEN", "")
    try:
        parsed = urlparse(base)
        valid_base = parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and not parsed.port
    except ValueError:
        valid_base = False
    if not valid_base or not token:
        raise HTTPException(503, "La recepción de publicaciones sociales aún no está habilitada.")
    metadata = await recover_metadata(url, platform)
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            reply = await client.post(base + "/v1/social/ingest", headers={"X-Atlas-Token": token},
                                      json={"url": url, "country": country, "platform": platform,
                                            "source_type": "user_contributed", "intake_channel": "carly_paste_link", **metadata})
            reply.raise_for_status()
            row = reply.json()
            candidate_id = row["id"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502, "No pudimos guardar la publicación. Intenta nuevamente.") from None
    return {"source_url": url, "platform": platform, "country": country,
            "candidate_id": candidate_id, "candidate_saved": True, "saved": False,
            "in_inventory": False, "live_verified": False, "status": "pending_review",
            "metadata_status": metadata.get("metadata_status"),
            "vehicle_card": row.get("vehicle_card"),
            "message": "Recibimos la publicación. Revisaremos el vehículo y su disponibilidad."}
