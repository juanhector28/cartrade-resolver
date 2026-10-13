"""Opt-in link-first buyer-intent intake. Disabled until all release gates pass.

This is not a loan application, credit decision, seller notification or Atlas import.
"""
from __future__ import annotations

import os
import re
import ipaddress
from urllib.parse import urlsplit
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl

from . import rate_limit

router = APIRouter()


class BuyerIntentRequest(BaseModel):
    request_id: UUID
    buyer_contact: str = Field(min_length=8, max_length=25)
    contact_channel: Literal["whatsapp"] = "whatsapp"
    listing_url: HttpUrl
    car_name: str | None = Field(default=None, min_length=2, max_length=200)
    price_usd: int | None = Field(default=None, ge=500, le=200000)
    country: Literal["sv", "gt", "cr", "hn", "ni", "pa"] = "sv"
    source: Literal["paste_link"] = "paste_link"
    consent_to_contact: Literal[True]


def validate_intent_link(value: str) -> str:
    """Validate a user-provided link without fetching or indexing its destination.

    URLs are untrusted, especially when viewed later by an operator. This is an
    intake-only feature and does not grant robots, scraping or photo permissions.
    """
    if len(value) > 2048:
        raise HTTPException(422, "El enlace es demasiado largo")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme != "https" or not host or parsed.port is not None
            or parsed.username is not None or parsed.password is not None
            or len(host) > 253
            or host in {"localhost", "local", "internal"}
            or host.endswith((".localhost", ".local", ".internal"))
            or "." not in host
        ):
            raise ValueError("unsafe URL")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("IP-literal URL")
    except (ValueError, TypeError):
        raise HTTPException(422, "Introduce un enlace HTTPS público válido")
    return value


@router.post("/buyer-intents", status_code=201)
async def create_buyer_intent(body: BuyerIntentRequest, request: Request):
    if os.environ.get("BUYER_INTENTS_ENABLED") != "1":
        raise HTTPException(503, "La recepción de solicitudes aún no está disponible")

    table = os.environ.get("BUYER_INTENTS_TABLE", "")
    database = getattr(request.app.state, "buyer_intents_db", None)
    if not database or not re.fullmatch(r"[a-z][a-z0-9_]{2,48}", table):
        raise HTTPException(503, "La recepción de solicitudes no está configurada")

    # Browser-origin check is defense in depth, not authentication.
    origins = {s.strip() for s in os.environ.get(
        "BUYER_INTENTS_ORIGINS", "https://cartrade.live,https://www.cartrade.live"
    ).split(",") if s.strip()}
    if request.headers.get("origin") not in origins:
        raise HTTPException(403, "Origen no permitido")

    url = validate_intent_link(str(body.listing_url))

    phone = re.sub(r"\D", "", body.buyer_contact)
    if not 8 <= len(phone) <= 15:
        raise HTTPException(422, "Número de contacto inválido")

    # Do not trust client-supplied X-Forwarded-For for rate limiting.
    peer = request.client.host if request.client else "unknown"
    allowed, _ = rate_limit.check("buyer-intent:" + peer)
    if not allowed:
        raise HTTPException(429, "Demasiadas solicitudes, intenta más tarde")

    row = {
        "request_id": str(body.request_id),
        "buyer_contact": phone,
        "contact_channel": "whatsapp",
        "listing_url": url,
        "car_name": body.car_name.strip() if body.car_name else "Vehículo pendiente de identificar",
        "price_usd": body.price_usd,
        "country": body.country,
        "source": "paste_link",
        "consent_to_contact": True,
        "status": "received",
    }
    try:
        database.table(table).upsert(row, on_conflict="request_id", ignore_duplicates=True).execute()
    except Exception:
        # Never log private contact information or return database error text.
        raise HTTPException(503, "No se pudo registrar la solicitud. Inténtalo otra vez")

    return JSONResponse(
        status_code=201,
        content={"status": "received", "request_id": str(body.request_id)},
        headers={"Cache-Control": "no-store"},
    )
