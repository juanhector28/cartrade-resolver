"""Customer-safe financing intake bridge.

This path captures only facts the customer can truthfully provide. It persists a
CHECKS_PENDING intake in CarTrade Transactions and never submits to Router.
Verified income, bureau/fraud results and lender pricing belong to later stages.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator


SUPPORTED_COUNTRIES = {"SV", "GT", "CR", "PA"}


class CustomerBorrowerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=2, max_length=160)
    monthly_income_reported: float = Field(gt=0)
    monthly_debt: float = Field(default=0, ge=0)


class CustomerVehicleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vehicle_ref: str = Field(min_length=3, max_length=300)
    make: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    year: int = Field(ge=1980, le=2100)
    purchase_price: float = Field(gt=0)
    market_value: float | None = Field(default=None, gt=0)


class CustomerFinancingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    down_payment: float = Field(default=0, ge=0)
    requested_amount: float | None = Field(default=None, gt=0)
    term_months: int = Field(default=60, ge=6, le=120)
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class CustomerFinancingIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    journey_id: str = Field(min_length=8, max_length=160)
    country: str
    borrower: CustomerBorrowerInput
    vehicle: CustomerVehicleInput
    financing: CustomerFinancingInput
    consents: list[dict[str, Any]] = Field(default_factory=list)
    trust_credentials: list[str] = Field(default_factory=list)

    @field_validator("country")
    @classmethod
    def supported_country(cls, value: str) -> str:
        country = value.upper()
        if country not in SUPPORTED_COUNTRIES:
            raise ValueError("unsupported financing country")
        return country


class FinancingIntakeBridgeError(RuntimeError):
    pass


class FinancingIntakeBridge:
    def __init__(self, *, base_url: str | None = None, api_key: str | None = None, timeout: float = 12.0, client=None):
        self.base_url = (base_url or os.getenv("CARTRADE_TRANSACTIONS_URL", "https://cartrade-transactions.vercel.app")).rstrip("/")
        self.api_key = (api_key if api_key is not None else os.getenv("CARTRADE_TRANSACTIONS_API_KEY", "")).strip()
        self.timeout = timeout
        self._client = client

    def _auth_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise FinancingIntakeBridgeError("transactions credential is not configured")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    @staticmethod
    def idempotency_key(user_id: str, journey_id: str, vehicle_ref: str) -> str:
        raw = f"{user_id}|{journey_id}|{vehicle_ref}".encode("utf-8")
        return "webint:" + hashlib.sha256(raw).hexdigest()[:48]

    def submit(self, *, user_id: str, body: CustomerFinancingIntake) -> dict[str, Any]:
        payload = body.model_dump()
        payload["user_subject"] = user_id
        payload["source_channel"] = "cartrade_web"
        idem = self.idempotency_key(user_id, body.journey_id, body.vehicle.vehicle_ref)
        headers = {
            **self._auth_headers(),
            "Idempotency-Key": idem,
            "Content-Type": "application/json",
        }
        try:
            if self._client is not None:
                response = self._client.post("/v1/financing/intakes", json=payload, headers=headers)
            else:
                with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
                    response = client.post("/v1/financing/intakes", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise FinancingIntakeBridgeError("transactions service unavailable") from exc

        if response.status_code >= 400:
            raise FinancingIntakeBridgeError(f"transactions intake returned HTTP {response.status_code}")
        try:
            result = response.json()
        except ValueError as exc:
            raise FinancingIntakeBridgeError("transactions intake returned invalid JSON") from exc

        if result.get("state") != "CHECKS_PENDING":
            raise FinancingIntakeBridgeError("transactions intake returned unexpected state")
        if result.get("router_submitted") is not False:
            raise FinancingIntakeBridgeError("customer intake crossed Router boundary")
        if result.get("contractual") is not False or result.get("integration_mode") != "SHADOW":
            raise FinancingIntakeBridgeError("customer intake violated SHADOW boundary")

        return {
            "financing_intake_id": result.get("financing_intake_id"),
            "journey_id": result.get("journey_id"),
            "vehicle_ref": result.get("vehicle_ref"),
            "status": "CHECKS_PENDING",
            "requested_amount": result.get("requested_amount"),
            "currency": result.get("currency", "USD"),
            "next_required": result.get("next_required") or [],
            "integration_mode": "SHADOW",
            "contractual": False,
            "router_submitted": False,
            "displayable_approval": False,
        }
