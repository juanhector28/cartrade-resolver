from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Protocol
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field, model_validator


def now() -> datetime:
    return datetime.now(UTC)


class ApplicationStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    OFFERED = "offered"
    ACCEPTED = "accepted"


class Money(BaseModel):
    amount: int = Field(gt=0, description="Minor currency units")
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class Buyer(BaseModel):
    external_id: str
    country: str = Field(pattern=r"^[A-Z]{2}$")
    monthly_income: Money
    monthly_debt: Money = Field(default_factory=lambda: Money(amount=1, currency="USD"))


class Vehicle(BaseModel):
    external_id: str
    make: str
    model: str
    year: int = Field(ge=1990, le=2100)
    price: Money
    mileage_km: int = Field(ge=0)


class CreateApplication(BaseModel):
    cartrade_reference: str
    buyer: Buyer
    vehicle: Vehicle
    down_payment: Money
    requested_amount: Money
    consent_reference: str

    @model_validator(mode="after")
    def validate_transaction(self):
        currencies = {
            self.buyer.monthly_income.currency,
            self.vehicle.price.currency,
            self.down_payment.currency,
            self.requested_amount.currency,
        }
        if len(currencies) != 1:
            raise ValueError("All monetary fields must use the same currency")
        if self.down_payment.amount + self.requested_amount.amount != self.vehicle.price.amount:
            raise ValueError("down_payment + requested_amount must equal vehicle price")
        return self


class Offer(BaseModel):
    id: str
    application_id: str
    bank_id: str
    status: str
    approved_amount: Money
    term_months: int
    annual_rate_percent: float
    monthly_payment: Money
    conditions: list[str]
    expires_at: datetime


class Event(BaseModel):
    type: str
    at: datetime
    metadata: dict = Field(default_factory=dict)


class Application(BaseModel):
    id: str
    status: ApplicationStatus
    payload: CreateApplication
    offers: list[Offer] = Field(default_factory=list)
    accepted_offer_id: str | None = None
    timeline: list[Event] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class Store(Protocol):
    async def create(self, app: Application, idempotency_key: str) -> Application: ...
    async def get(self, application_id: str) -> Application | None: ...
    async def save(self, app: Application) -> None: ...


class MemoryStore:
    """Development store. Replace with PostgresStore without changing API/domain logic."""

    def __init__(self):
        self._apps: dict[str, Application] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def create(self, app: Application, idempotency_key: str) -> Application:
        async with self._lock:
            existing_id = self._idempotency.get(idempotency_key)
            if existing_id:
                existing = self._apps[existing_id]
                if existing.payload != app.payload:
                    raise HTTPException(status_code=409, detail="Idempotency key reused with different payload")
                return existing
            self._apps[app.id] = app
            self._idempotency[idempotency_key] = app.id
            return app

    async def get(self, application_id: str) -> Application | None:
        return self._apps.get(application_id)

    async def save(self, app: Application) -> None:
        async with self._lock:
            self._apps[app.id] = app


class BankAdapter(Protocol):
    bank_id: str
    async def request_offer(self, application: Application) -> Offer | None: ...


class AtlantidaSandboxAdapter:
    bank_id = "banco-atlantida-sandbox"

    async def request_offer(self, application: Application) -> Offer | None:
        data = application.payload
        if data.buyer.country not in {"SV", "HN", "GT"}:
            return None
        if data.vehicle.year < now().year - 12:
            return None
        down_payment_ratio = data.down_payment.amount / data.vehicle.price.amount
        debt_ratio = (
            data.buyer.monthly_debt.amount
            / max(data.buyer.monthly_income.amount, 1)
        )
        if down_payment_ratio < 0.10 or debt_ratio > 0.45:
            return None

        annual_rate = 10.5
        term = 60
        principal = data.requested_amount.amount
        monthly_rate = annual_rate / 100 / 12
        payment = round(principal * monthly_rate / (1 - (1 + monthly_rate) ** -term))
        fingerprint = sha256(f"{application.id}:{self.bank_id}".encode()).hexdigest()[:16]
        return Offer(
            id=f"off_{fingerprint}",
            application_id=application.id,
            bank_id=self.bank_id,
            status="conditional_approval",
            approved_amount=data.requested_amount,
            term_months=term,
            annual_rate_percent=annual_rate,
            monthly_payment=Money(amount=payment, currency=data.requested_amount.currency),
            conditions=["TrustPass verified", "Vehicle inspection approved"],
            expires_at=now() + timedelta(days=14),
        )


store: Store = MemoryStore()
adapters: list[BankAdapter] = [AtlantidaSandboxAdapter()]
app = FastAPI(title="Atlas Financing Router", version="0.1.0")


async def require_application(application_id: str) -> Application:
    application = await store.get(application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@app.get("/health")
async def health():
    return {"status": "ok", "service": "atlas-financing-router", "version": "0.1.0"}


@app.post("/v1/applications", response_model=Application, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: CreateApplication,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8)],
):
    timestamp = now()
    application = Application(
        id=f"app_{uuid4().hex}",
        status=ApplicationStatus.DRAFT,
        payload=payload,
        timeline=[Event(type="application.created", at=timestamp)],
        created_at=timestamp,
        updated_at=timestamp,
    )
    return await store.create(application, idempotency_key)


@app.post("/v1/applications/{application_id}/submit", response_model=Application)
async def submit_application(application_id: str):
    application = await require_application(application_id)
    if application.status != ApplicationStatus.DRAFT:
        raise HTTPException(status_code=409, detail="Only draft applications can be submitted")

    application.status = ApplicationStatus.SUBMITTED
    application.timeline.append(Event(type="application.submitted", at=now()))
    offers = [
        offer
        for offer in await asyncio.gather(
            *(adapter.request_offer(application) for adapter in adapters)
        )
        if offer is not None
    ]
    application.offers = offers
    application.status = ApplicationStatus.OFFERED if offers else ApplicationStatus.SUBMITTED
    application.updated_at = now()
    application.timeline.append(
        Event(type="offers.received", at=application.updated_at, metadata={"count": len(offers)})
    )
    await store.save(application)
    return application


@app.get("/v1/applications/{application_id}/offers", response_model=list[Offer])
async def list_offers(application_id: str):
    return (await require_application(application_id)).offers


@app.post("/v1/applications/{application_id}/offers/{offer_id}/accept", response_model=Application)
async def accept_offer(application_id: str, offer_id: str):
    application = await require_application(application_id)
    if application.status != ApplicationStatus.OFFERED:
        raise HTTPException(status_code=409, detail="Application is not ready for offer acceptance")
    offer = next((item for item in application.offers if item.id == offer_id), None)
    if offer is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    if offer.expires_at <= now():
        raise HTTPException(status_code=409, detail="Offer has expired")

    application.accepted_offer_id = offer.id
    application.status = ApplicationStatus.ACCEPTED
    application.updated_at = now()
    application.timeline.append(
        Event(type="offer.accepted", at=application.updated_at, metadata={"offer_id": offer.id})
    )
    await store.save(application)
    return application


@app.get("/v1/applications/{application_id}/timeline", response_model=list[Event])
async def timeline(application_id: str):
    return (await require_application(application_id)).timeline
