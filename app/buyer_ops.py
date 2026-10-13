"""Private operational inbox for CarTrade buyer requests.

Feature-off by default. Supabase Auth email OTP issues per-operator access
sessions, which are separately checked against active private staff records.
The HTML shell contains no customer records and the JSON API requires JWT.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import rate_limit

router = APIRouter()
_COLUMNS = (
    "request_id,created_at,buyer_contact,contact_channel,listing_url,"
    "car_name,price_usd,country,status,consent_recorded_at"
)


class OperatorEmail(BaseModel):
    email: str = Field(min_length=5, max_length=254)


class OperatorVerifyCode(OperatorEmail):
    code: str = Field(min_length=6, max_length=12)


def _auth_client():
    """Use a fresh low-privilege Auth client, never the shared service-role client.

    OTP verification can mutate Auth client session state. Isolating that state
    prevents one operator's token from becoming the server's global DB identity.
    """
    url = os.environ.get("SUPABASE_URL", "")
    public_key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
    if not url.startswith("https://") or not public_key:
        raise HTTPException(status_code=503, detail="Acceso de operadores no configurado")
    from supabase import create_client
    return create_client(url, public_key)


def _normalize_email(raw: str) -> str:
    email = raw.strip().lower()
    if not re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", email):
        raise HTTPException(status_code=422, detail="Correo inválido")
    return email


def _staff_is_active(database, staff_table: str, user_id: str, email: str) -> bool:
    rows = (
        database.table(staff_table)
        .select("user_id,role,active,email")
        .eq("user_id", user_id)
        .eq("active", True)
        .limit(1)
        .execute()
        .data
    ) or []
    return bool(rows and rows[0].get("role") in ("admin", "operator")
                and str(rows[0].get("email", "")).lower() == email)


class UpdateBuyerIntentStatus(BaseModel):
    status: Literal["received", "in_review", "contacted", "closed"]


def _ready(request: Request):
    if os.environ.get("BUYER_OPS_ENABLED") != "1":
        raise HTTPException(status_code=404, detail="Not found")

    table = os.environ.get("BUYER_INTENTS_TABLE", "")
    staff_table = os.environ.get("BUYER_OPS_STAFF_TABLE", "buyer_ops_staff")
    database = getattr(request.app.state, "buyer_intents_db", None)
    if (not re.fullmatch(r"[a-z][a-z0-9_]{2,48}", table)
            or not re.fullmatch(r"[a-z][a-z0-9_]{2,48}", staff_table)
            or database is None):
        raise HTTPException(status_code=503, detail="Bandeja no configurada")
    return database, table, staff_table


def _auth_rate_limit(request: Request, namespace: str):
    ip = request.client.host if request.client else "unknown"
    allowed, _ = rate_limit.check(namespace + ":" + ip)
    if not allowed:
        raise HTTPException(status_code=429, detail="Demasiados intentos")


def _authorize(request: Request, authorization: str | None):
    database, table, staff_table = _ready(request)
    _auth_rate_limit(request, "buyer-ops-auth")

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not 20 <= len(token) <= 4096:
        raise HTTPException(status_code=401, detail="Autenticación requerida")

    # Supabase Auth verifies the JWT remotely. A signature-looking token is
    # never enough to authorize access. Then verify individual staff membership.
    try:
        auth_result = _auth_client().auth.get_user(token)
        user = auth_result.user
        if user is None or not user.id or not user.email:
            raise ValueError("Missing Auth identity")
        authorized = _staff_is_active(database, staff_table, str(user.id), user.email.lower())
    except Exception:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    if not authorized:
        raise HTTPException(status_code=403, detail="Operador no autorizado")
    return database, table


@router.post("/ops/auth/start", status_code=202)
async def operator_start(body: OperatorEmail, request: Request):
    database, _, staff_table = _ready(request)
    _auth_rate_limit(request, "buyer-ops-otp")
    email = _normalize_email(body.email)
    allowed, _ = rate_limit.check("buyer-ops-email:" + hashlib.sha256(email.encode()).hexdigest())
    if not allowed:
        raise HTTPException(status_code=429, detail="Demasiados intentos")

    # Prevent OTP delivery to unrelated customer Auth users. Do not leak
    # operator membership, even when an email is not registered.
    try:
        staff = (
            database.table(staff_table).select("user_id")
            .eq("email", email).eq("active", True).limit(1).execute().data
        ) or []
        if staff:
            _auth_client().auth.sign_in_with_otp({
                "email": email,
                "options": {"should_create_user": False}
            })
    except Exception:
        pass
    return JSONResponse(
        {"status": "if_authorized_code_sent"},
        status_code=202, headers={"Cache-Control": "no-store"},
    )


@router.post("/ops/auth/verify")
async def operator_verify(body: OperatorVerifyCode, request: Request):
    database, _, staff_table = _ready(request)
    _auth_rate_limit(request, "buyer-ops-verify")
    email = _normalize_email(body.email)
    try:
        auth_result = _auth_client().auth.verify_otp({
            "email": email, "token": body.code.strip(), "type": "email"
        })
        user = auth_result.user
        session = auth_result.session
        if (not user or not session or not session.access_token
                or str(user.email).lower() != email
                or not _staff_is_active(database, staff_table, str(user.id), email)):
            raise ValueError("Not approved")
    except Exception:
        raise HTTPException(status_code=401, detail="Código inválido o acceso no autorizado")

    # Access token stays in browser memory only; never log or include in URLs.
    return JSONResponse(
        {"access_token": session.access_token, "token_type": "bearer"},
        headers={"Cache-Control": "no-store"},
    )


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
