"""Private operational inbox for CarTrade buyer requests.

Feature-off by default. Authentication uses an operator-issued, high-entropy
bearer token whose SHA-256 hash is configured server-side. No public list route.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import rate_limit

router = APIRouter()
_COLUMNS = (
    "request_id,created_at,buyer_contact,contact_channel,listing_url,"
    "car_name,price_usd,country,status,consent_recorded_at"
)


class UpdateBuyerIntentStatus(BaseModel):
    status: Literal["received", "in_review", "contacted", "closed"]


def _ready(request: Request):
    if os.environ.get("BUYER_OPS_ENABLED") != "1":
        raise HTTPException(status_code=404, detail="Not found")

    token_hash = os.environ.get("BUYER_OPS_TOKEN_SHA256", "").lower()
    table = os.environ.get("BUYER_INTENTS_TABLE", "")
    database = getattr(request.app.state, "buyer_intents_db", None)
    if (
        not re.fullmatch(r"[a-f0-9]{64}", token_hash)
        or not re.fullmatch(r"[a-z][a-z0-9_]{2,48}", table)
        or database is None
    ):
        raise HTTPException(status_code=503, detail="Bandeja no configurada")
    return database, table, token_hash


def _authorize(request: Request, authorization: str | None):
    database, table, token_hash = _ready(request)

    # Read the direct socket peer, never unaudited X-Forwarded-For headers.
    ip = request.client.host if request.client else "unknown"
    allowed, _ = rate_limit.check("buyer-ops-auth:" + ip)
    if not allowed:
        raise HTTPException(status_code=429, detail="Demasiados intentos")

    scheme, _, token = (authorization or "").partition(" ")
    valid = (
        scheme.lower() == "bearer"
        and 32 <= len(token) <= 512
        and secrets.compare_digest(
            hashlib.sha256(token.encode("utf-8")).hexdigest(), token_hash
        )
    )
    if not valid:
        raise HTTPException(
            status_code=401,
            detail="Autenticación requerida",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return database, table


@router.get("/ops/solicitudes", response_class=HTMLResponse)
async def buyer_ops_page(request: Request):
    _ready(request)
    from .buyer_ops_page import PAGE

    return HTMLResponse(
        PAGE, headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'; "
                "img-src 'none'; form-action 'none'; frame-ancestors 'none'"
            ),
        }
    )


@router.get("/ops/api/solicitudes")
async def list_buyer_intents(
    request: Request,
    authorization: str | None = Header(default=None),
    offset: int = 0,
    limit: int = 50,
):
    database, table = _authorize(request, authorization)
    if not 0 <= offset <= 10000 or not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="Paginación inválida")
    try:
        result = (
            database.table(table)
            .select(_COLUMNS)
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=503, detail="Bandeja temporalmente no disponible")
    return JSONResponse(
        {"items": result.data or [], "offset": offset, "limit": limit},
        headers={"Cache-Control": "no-store"},
    )


@router.patch("/ops/api/solicitudes/{request_id}")
async def update_buyer_intent(
    request_id: UUID,
    body: UpdateBuyerIntentStatus,
    request: Request,
    authorization: str | None = Header(default=None),
):
    database, table = _authorize(request, authorization)
    try:
        result = (
            database.table(table)
            .update({"status": body.status})
            .eq("request_id", str(request_id))
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo actualizar la solicitud")
    if not result.data:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    return JSONResponse(
        {"request_id": str(request_id), "status": body.status},
        headers={"Cache-Control": "no-store"},
    )
