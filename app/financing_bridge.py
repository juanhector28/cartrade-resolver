"""Server-side bridge from CarTrade web journeys to cartrade-transactions.

The browser never receives the transactions service credential. This bridge is
SHADOW-only: a non-SHADOW or contractual response is rejected.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator


SUPPORTED_COUNTRIES = {"SV", "GT", "CR", "PA"}


class BorrowerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=2, max_length=160)
    monthly_income_reported: float = Field(gt=0)
    monthly_income_verified: float = Field(gt=0)
    monthly_debt: float = Field(default=0, ge=0)


class VehicleInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    vehicle_ref: str = Field(min_length=3, max_length=300)
    make: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    year: int = Field(ge=1980, le=2100)
    purchase_price: float = Field(gt=0)
    market_value: float = Field(gt=0)
    vin_token: str | None = Field(default=None, max_length=300)


class FinancingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested_amount: float = Field(gt=0)
    down_payment: float = Field(ge=0)
    term_months: int = Field(ge=6, le=120)
    annual_rate_pct: float = Field(gt=0, le=100)
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class ChecksInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bureau_score: int = Field(ge=0, le=1000)
    fraud_score: float = Field(ge=0, le=100)


class FinancingJourneyInput(BaseModel):
    """Facts available only after the prequalification checks have run.

    In the SHADOW pilot these facts are analytical inputs, never a borrower-facing
    approval. Institution and product are deliberately not client-selectable.
    """

    model_config = ConfigDict(extra="forbid")
    journey_id: str = Field(min_length=8, max_length=160)
    country: str
    borrower: BorrowerInput
    vehicle: VehicleInput
    financing: FinancingInput
    checks: ChecksInput
    consents: list[dict[str, Any]] = Field(default_factory=list)
    trust_credentials: list[str] = Field(default_factory=list)

    @field_validator("country")
    @classmethod
    def supported_country(cls, value: str) -> str:
        country = value.upper()
        if country not in SUPPORTED_COUNTRIES:
            raise ValueError("unsupported financing country")
        return country


class FinancingBridgeError(RuntimeError):
    pass


class FinancingBridgeNotConfigured(FinancingBridgeError):
    pass


class FinancingBridge:
    def __init__(self, *, base_url: str | None = None, api_key: str | None = None, timeout: float = 12.0, client=None):
        self.base_url = (base_url or os.getenv("CARTRADE_TRANSACTIONS_URL", "https://cartrade-transactions.vercel.app")).rstrip("/")
        self.api_key = (api_key if api_key is not None else os.getenv("CARTRADE_TRANSACTIONS_API_KEY", "")).strip()
        self.timeout = timeout
        self._client = client

    def _route(self) -> tuple[str, str]:
        # SHADOW pilot route is server-owned. The browser cannot choose a lender.
        institution = os.getenv("CARTRADE_FINANCING_INSTITUTION_ID", "sandbox_lender").strip()
        product = os.getenv("CARTRADE_FINANCING_PRODUCT_ID", "used_vehicle_standard").strip()
        if not institution or not product:
            raise FinancingBridgeNotConfigured("financing route is not configured")
        return institution, product

    @staticmethod
    def idempotency_key(user_id: str, journey_id: str, vehicle_ref: str) -> str:
        raw = f"{user_id}|{journey_id}|{vehicle_ref}".encode("utf-8")
        return "webfin:" + hashlib.sha256(raw).hexdigest()[:48]

    def build_payload(self, body: FinancingJourneyInput) -> dict[str, Any]:
        institution, product = self._route()
        vehicle = body.vehicle.model_dump(exclude={"vehicle_ref"})
        return {
            "institution_id": institution,
            "product_id": product,
            "country": body.country,
            "borrower": body.borrower.model_dump(),
            "vehicle": vehicle,
            "financing": body.financing.model_dump(),
            "checks": body.checks.model_dump(),
            "consents": body.consents,
            "trust_credentials": body.trust_credentials,
            "source_channel": "cartrade_web",
        }

    def submit(self, *, user_id: str, body: FinancingJourneyInput) -> dict[str, Any]:
        if not self.api_key:
            raise FinancingBridgeNotConfigured("transactions credential is not configured")
        payload = self.build_payload(body)
        idem = self.idempotency_key(user_id, body.journey_id, body.vehicle.vehicle_ref)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Idempotency-Key": idem,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            if self._client is not None:
                response = self._client.post("/v1/financing/requests", json=payload, headers=headers)
            else:
                with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
                    response = client.post("/v1/financing/requests", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise FinancingBridgeError("transactions service unavailable") from exc

        if response.status_code >= 400:
            raise FinancingBridgeError(f"transactions service returned HTTP {response.status_code}")
        try:
            result = response.json()
        except ValueError as exc:
            raise FinancingBridgeError("transactions service returned invalid JSON") from exc

        router = result.get("router") or {}
        if router.get("integration_mode") != "SHADOW" or router.get("contractual") is not False:
            raise FinancingBridgeError("transactions response violated SHADOW boundary")

        # Return only the customer-journey safe envelope. A Router recommendation is
        # analytical evidence and must not be rendered as lender approval.
        return {
            "status": result.get("state"),
            "financing_request_id": result.get("financing_request_id"),
            "external_application_id": result.get("external_application_id"),
            "router_application_id": router.get("application_id"),
            "shadow_recommendation": router.get("recommendation"),
            "policy_version": router.get("policy_version"),
            "integration_mode": "SHADOW",
            "contractual": False,
            "borrower_approval": None,
            "displayable_approval": False,
        }
