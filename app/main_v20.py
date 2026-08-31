"""Carly v20: authenticated server-side financing handoff.

This layer leaves recommendation logic untouched. It exposes three financing
boundaries:
- /financing/intake captures customer facts and stops at CHECKS_PENDING.
- /financing/intakes/{id} returns owner-bound customer-safe status.
- /financing/start accepts evidence-complete facts and may reach Router SHADOW.

The downstream Transactions credential never reaches the browser and no path can
produce a contractual borrower approval.
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
from .financing_intake_bridge import (
    CustomerFinancingIntake,
    FinancingIntakeBridge,
    FinancingIntakeBridgeError,
    FinancingIntakeNotFound,
)
from .public_auth import PublicAuthConfigError, public_supabase_config


app = v19.app
commercial = v19.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v20-financing-bridge"

_prior_financing_for_car = commercial.financing_for_car


def _financing_with_action(car: dict) -> dict:
    result = _prior_financing_for_car(car)
    vehicle_ref = car.get("id") or car.get("url")
    price = car.get("price_usd")
    year = car.get("year")
    prefill = {
        "vehicle": {
            "vehicle_ref": vehicle_ref,
            "make": car.get("make"),
            "model": car.get("model"),
            "year": year,
            "purchase_price": price,
            "market_value": car.get("market_value"),
        }
    }
    result["action"] = {
        "id": "start_financing_intake",
        "label": "Ver financiamiento",
        "method": "POST",
        "endpoint": "/financing/intake",
        "requires_auth": True,
        "integration_mode": "SHADOW",
        "prefill": prefill,
        "collect": [
            "borrower.full_name",
            "borrower.monthly_income_reported",
            "borrower.monthly_debt",
            "financing.down_payment",
            "financing.term_months",
        ],
        "result_state": "CHECKS_PENDING",
        "status_endpoint_template": "/financing/intakes/{financing_intake_id}",
    }
    return result


commercial.financing_for_car = _financing_with_action


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


@app.get("/auth/config")
def auth_config():
    try:
        return public_supabase_config()
    except PublicAuthConfigError as exc:
        raise HTTPException(status_code=503, detail="public authentication not configured") from exc


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


@app.post("/financing/intake")
def financing_intake(
    body: CustomerFinancingIntake,
    authorization: str | None = Header(default=None),
):
    user_id = _authenticated_user_id(authorization)
    try:
        return FinancingIntakeBridge().submit(user_id=user_id, body=body)
    except FinancingIntakeBridgeError as exc:
        raise HTTPException(status_code=502, detail="financing intake unavailable") from exc


@app.get("/financing/intakes/{intake_id}")
def financing_intake_status(
    intake_id: str,
    authorization: str | None = Header(default=None),
):
    user_id = _authenticated_user_id(authorization)
    try:
        return FinancingIntakeBridge().get(user_id=user_id, intake_id=intake_id)
    except FinancingIntakeNotFound as exc:
        raise HTTPException(status_code=404, detail="financing intake not found") from exc
    except FinancingIntakeBridgeError as exc:
        raise HTTPException(status_code=502, detail="financing intake unavailable") from exc


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
