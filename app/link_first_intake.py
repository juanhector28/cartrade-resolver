"""CarTrade link-first intake router, NOT mounted on production by default.

A buyer may request help with any public HTTPS listing link, even if no
scraper exists. This module NEVER fetches or indexes the URL. A request is only
acknowledged after a private database write. Keep feature flags OFF until the
privacy notice, retention policy and abuse-protection rollout are approved.
"""
from __future__ import annotations

import ipaddress
import os
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl

router = APIRouter()


class BuyerLinkRequest(BaseModel):
    request_id: UUID
    listing_url: HttpUrl
    buyer_contact: str = Field(min_length=8, max_length=25)
    contact_channel: Literal["whatsapp"] = "whatsapp"
    country: Literal["sv", "gt", "cr", "hn", "ni", "pa"] = "sv"
    source: Literal["paste_link"] = "paste_link"
    consent_to_contact: Literal[True]


def public_https_listing(value: str) -> str:
    """Accept a URL as buyer-provided input, not as permission to scrape it."""
    if len(value) > 2048:
        raise HTTPException(422, "Enlace demasiado largo")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme != "https" or not host or len(host) > 253
            or parsed.username is not None or parsed.password is not None
            or parsed.port is not None or "." not in host
            or host in ("localhost", "local", "internal")
            or host.endswith((".localhost", ".local", ".internal"))
        ):
            raise ValueError("unsupported link")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("IP address not allowed")
    except (ValueError, TypeError):
        raise HTTPException(422, "Usa un enlace HTTPS público")
    return value


def _configured(request: Request):
    if os.getenv("LINK_FIRST_INTAKE_ENABLED") != "1":
        raise HTTPException(503, "La recepción de solicitudes aún no está habilitada")
    table = os.getenv("LINK_FIRST_STORE_TABLE", "")
    db = getattr(request.app.state, "link_first_db", None)
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,48}", table) or db is None:
        raise HTTPException(503, "Recepción no configurada")
    # A real abuse-protection check must be bound by the app before enabling.
    verifier = getattr(request.app.state, "link_first_abuse_verifier", None)
    if not callable(verifier):
        raise HTTPException(503, "Protección contra abuso no configurada")
    return db, table, verifier


@router.post("/buyer-intents", status_code=201)
async def capture_link_first(body: BuyerLinkRequest, request: Request):
    db, table, verify_abuse = _configured(request)
    origins = {
        origin.strip() for origin in os.getenv(
            "LINK_FIRST_ALLOWED_ORIGINS", "https://cartrade.live"
        ).split(",") if origin.strip()
    }
    # Origin checking is a defense-in-depth measure, not authentication.
    if request.headers.get("origin") not in origins:
        raise HTTPException(403, "Origen no autorizado")

    url = public_https_listing(str(body.listing_url))
    phone = re.sub(r"\D", "", body.buyer_contact)
    if not 8 <= len(phone) <= 15:
        raise HTTPException(422, "Número de WhatsApp no válido")

    # Verifier must enforce a real challenge/rate-limit; the endpoint cannot
    # infer trusted identity from request.headers['X-Forwarded-For'].
    try:
        allowed = bool(await verify_abuse(request))
    except Exception:
        allowed = False
    if not allowed:
        raise HTTPException(429, "Demasiadas solicitudes o verificación fallida")

    row = {
        "request_id": str(body.request_id),
        "listing_url": url,
        "buyer_contact": phone,
        "contact_channel": "whatsapp",
        "country": body.country,
        "source": "paste_link",
        "car_name": "Vehículo pendiente de identificar",
        "price_usd": None,
        "consent_to_contact": True,
        "status": "received",
    }
    try:
        db.table(table).upsert(
            row, on_conflict="request_id", ignore_duplicates=True
        ).execute()
    except Exception:
        # Never expose phone, URLs, credentials or DB errors in responses.
        raise HTTPException(503, "No se pudo registrar la solicitud")
    return JSONResponse(
        status_code=201,
        content={"status": "received", "request_id": str(body.request_id)},
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
