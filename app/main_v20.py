"""Carly v20: authenticated server-side financing handoff.

This layer leaves recommendation logic untouched. It adds a narrow BFF endpoint
that forwards an authenticated CarTrade financing journey to the isolated
cartrade-transactions service. The downstream credential never reaches the
browser and every result remains SHADOW/non-contractual.
"""
from __future__ import annotations

import os

from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse

from . import main as legacy
from . import main_v19 as v19
from .financing_bridge import (
    FinancingBridge,
    FinancingBridgeError,
    FinancingBridgeNotConfigured,
    FinancingJourneyInput,
)


app = v19.app
commercial = v19.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v20-financing-bridge"


def _authenticated_user_id(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="authentication required")
    if legacy.supabase is None:
        raise HTTPException(status_code=503, detail="authentication service unavailable")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="authentication required")
    try:
        response = legacy.supabase.auth.get_user(token)
        user = getattr(response, "user", None)
        user_id = str(getattr(user, "id", "") or "").strip()
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid session") from exc
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid session")
    return user_id


@app.get("/financing/readiness")
def financing_readiness():
    configured = bool(os.getenv("CARTRADE_TRANSACTIONS_API_KEY", "").strip())
    payload = {
        "status": "not_ready",
        "service": "cartrade-resolver",
        "financing_bridge": "v20",
        "integration_mode": "SHADOW",
        "transactions_configured": configured,
        "transactions_authenticated": False,
        "requires_authenticated_user": True,
    }
    if not configured:
        payload["status"] = "not_configured"
        return JSONResponse(status_code=503, content=payload)
    try:
        FinancingBridge().check_authenticated_access()
    except (FinancingBridgeNotConfigured, FinancingBridgeError):
        return JSONResponse(status_code=503, content=payload)
    payload["status"] = "ready"
    payload["transactions_authenticated"] = True
    return payload


@app.post("/financing/start")
def financing_start(
    body: FinancingJourneyInput,
    authorization: str | None = Header(default=None),
):
    user_id = _authenticated_user_id(authorization)
    try:
        return FinancingBridge().submit(user_id=user_id, body=body)
    except FinancingBridgeNotConfigured as exc:
        raise HTTPException(status_code=503, detail="financing bridge not configured") from exc
    except FinancingBridgeError as exc:
        raise HTTPException(status_code=502, detail="financing service unavailable") from exc
