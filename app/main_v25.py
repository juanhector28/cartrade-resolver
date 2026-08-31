"""CarTrade v25: fast transaction UX support and Router SHADOW pilot intake.

Adds two narrowly scoped capabilities on top of v20:
1. Carly understands field/rural work answers deterministically, preventing the
   repeated "what will you use it for?" loop without adding LLM calls.
2. A PII-free, rate-limited browser endpoint mirrors a financing profile to the
   existing sandbox Router rail. It is SHADOW-only and can never create a
   contractual approval, offer, or funding event.

The public pilot endpoint deliberately does NOT accept name, phone, DUI, bureau
facts, or other identity data. Router sees a synthetic CarTrade shadow applicant
plus the actual vehicle and customer-reported affordability numbers.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import carly_fastpath
from . import main_preview as preview
from . import main_v20 as v20
from . import rate_limit
from .financing_bridge import FinancingBridgeError, FinancingBridgeNotConfigured
from .financing_intake_bridge import CustomerFinancingIntake
from .pilot_financing_promoter import (
    PILOT_EVIDENCE_MODE,
    PILOT_INSTITUTION_ID,
    PILOT_PRODUCT_ID,
    SandboxPilotFinancingBridge,
    build_synthetic_shadow_journey,
)


app = v20.app
v20.commercial.RUNTIME_COMPOSITION = "commercial-v25-transaction-router"


# ---------------------------------------------------------------------------
# Carly field-work intake repair
# ---------------------------------------------------------------------------

_FIELD_WORK_RE = re.compile(
    r"\b(?:campo|trabajo\s+de\s+campo|finca|fincas|rural|agricultur[ao]|"
    r"agricola|agr[ií]cola|ganader[ií]a|ganadero|terracer[ií]a|terraceria|"
    r"camino(?:s)?\s+de\s+tierra|terreno(?:s)?\s+(?:dif[ií]cil|rural|irregular)|"
    r"obra|construcci[oó]n)\b",
    re.I,
)


def _role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "").lower()
    return str(getattr(message, "role", "") or "").lower()


def _content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _field_work_present(messages: list[Any] | None) -> bool:
    text = "\n".join(_content(m) for m in (messages or []) if _role(m) == "user")
    return bool(_FIELD_WORK_RE.search(text))


def _augment_field_work(messages: list[Any] | None) -> list[dict[str, str]]:
    """Add a parser-only work hint while preserving the buyer's actual words."""
    rows = [{"role": _role(m), "content": _content(m)} for m in (messages or [])]
    if not rows or not _field_work_present(rows):
        return rows
    for idx in range(len(rows) - 1, -1, -1):
        if rows[idx]["role"] == "user":
            rows[idx] = {
                **rows[idx],
                "content": rows[idx]["content"] + "\n[parser hint: vehiculo de trabajo, herramientas y terreno rural]",
            }
            break
    return rows


_original_extract_fast_profile = preview.extract_fast_profile
_original_deterministic_reply = preview.deterministic_intake_reply


def _v25_extract_fast_profile(messages: list[Any] | None, country: str | None = None):
    return _original_extract_fast_profile(_augment_field_work(messages), country=country)


def _v25_deterministic_reply(messages: list[Any] | None, country: str | None = None):
    augmented = _augment_field_work(messages)
    reply = _original_deterministic_reply(augmented, country=country)

    # If the buyer just clarified "campo/finca/rural", let Carly ask the richer
    # budget question instead of forcing the generic monthly-payment blocker.
    if _field_work_present(messages) and reply == "Entendido. ¿Qué cuota mensual te queda cómoda?":
        return None

    # Generic loop fuse: never emit the exact same deterministic question twice
    # when the buyer has answered in between. Ambiguous cases fall back to Carly.
    if reply:
        last_assistant_idx = None
        for idx in range(len(list(messages or [])) - 1, -1, -1):
            if _role(list(messages or [])[idx]) == "assistant":
                last_assistant_idx = idx
                break
        if last_assistant_idx is not None:
            last_assistant = _content(list(messages or [])[last_assistant_idx])
            answered_after = any(
                _role(m) == "user" and _content(m).strip()
                for m in list(messages or [])[last_assistant_idx + 1 :]
            )
            if answered_after and _norm(last_assistant) == _norm(reply):
                return None
    return reply


# main_preview looks these names up from its module globals at request time, and
# the outer commercial wrappers reference the same module object.
preview.extract_fast_profile = _v25_extract_fast_profile
preview.deterministic_intake_reply = _v25_deterministic_reply


# ---------------------------------------------------------------------------
# Public PII-free Router SHADOW pilot bridge
# ---------------------------------------------------------------------------

class PilotVehicleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vehicle_ref: str = Field(min_length=3, max_length=300)
    make: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    year: int = Field(ge=1980, le=2100)
    purchase_price: float = Field(gt=0, le=500_000)
    market_value: float | None = Field(default=None, gt=0, le=500_000)


class PilotAffordabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    monthly_income_reported: float = Field(gt=0, le=1_000_000)
    monthly_debt: float = Field(default=0, ge=0, le=1_000_000)
    down_payment: float = Field(default=0, ge=0, le=500_000)
    term_months: int = Field(default=60, ge=24, le=96)
    income_type: str = Field(default="salaried", max_length=32)
    employment_tenure: str | None = Field(default=None, max_length=32)


class PublicPilotShadowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    journey_id: str = Field(min_length=8, max_length=160)
    country: str
    vehicle: PilotVehicleInput
    affordability: PilotAffordabilityInput

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        country = value.upper()
        if country not in {"SV", "GT", "CR", "PA"}:
            raise ValueError("unsupported financing country")
        return country


def _shadow_subject(journey_id: str) -> str:
    digest = hashlib.sha256(journey_id.encode("utf-8")).hexdigest()
    return "public-shadow:" + digest[:32]


@app.post("/financing/pilot-shadow")
def financing_pilot_shadow(body: PublicPilotShadowInput, request: Request):
    """Create one idempotent Router SHADOW application without accepting PII.

    This endpoint exists only for the current integration pilot. The downstream
    bridge is pinned to sandbox_lender/used_vehicle_standard and validates that
    Router remains non-contractual.
    """
    client_ip = request.client.host if request.client else "unknown"
    allowed, _remaining = rate_limit.check("financing-pilot:" + client_ip)
    if not allowed:
        raise HTTPException(status_code=429, detail="pilot rate limit exceeded")

    vehicle = body.vehicle
    affordability = body.affordability
    requested_amount = max(1.0, float(vehicle.purchase_price) - float(affordability.down_payment))
    market_value = float(vehicle.market_value or vehicle.purchase_price)
    applicant_tag = hashlib.sha256(body.journey_id.encode("utf-8")).hexdigest()[:8].upper()

    intake = CustomerFinancingIntake.model_validate(
        {
            "journey_id": body.journey_id,
            "country": body.country,
            "borrower": {
                "full_name": f"CARTRADE SHADOW {applicant_tag}",
                "monthly_income_reported": affordability.monthly_income_reported,
                "monthly_debt": affordability.monthly_debt,
            },
            "vehicle": {
                "vehicle_ref": vehicle.vehicle_ref,
                "make": vehicle.make,
                "model": vehicle.model,
                "year": vehicle.year,
                "purchase_price": vehicle.purchase_price,
                "market_value": market_value,
            },
            "financing": {
                "down_payment": affordability.down_payment,
                "requested_amount": requested_amount,
                "term_months": affordability.term_months,
                "currency": "USD",
            },
            "consents": [
                {
                    "type": "pilot_shadow_submission",
                    "accepted": True,
                    "scope": "non_contractual_integration_test",
                    "income_type": affordability.income_type,
                    "employment_tenure": affordability.employment_tenure,
                }
            ],
            "trust_credentials": [],
        }
    )

    journey = build_synthetic_shadow_journey(intake)
    try:
        result = SandboxPilotFinancingBridge().submit(
            user_id=_shadow_subject(body.journey_id),
            body=journey,
        )
    except FinancingBridgeNotConfigured as exc:
        raise HTTPException(status_code=503, detail="pilot financing bridge not configured") from exc
    except FinancingBridgeError as exc:
        raise HTTPException(status_code=502, detail="pilot financing bridge unavailable") from exc

    if result.get("integration_mode") != "SHADOW" or result.get("contractual") is not False:
        raise HTTPException(status_code=502, detail="pilot shadow boundary violated")

    return {
        "status": "ROUTER_SHADOW_SUBMITTED",
        "journey_id": body.journey_id,
        "router_application_id": result.get("router_application_id"),
        "financing_request_id": result.get("financing_request_id"),
        "external_application_id": result.get("external_application_id"),
        "shadow_recommendation": result.get("shadow_recommendation"),
        "policy_version": result.get("policy_version"),
        "institution_id": PILOT_INSTITUTION_ID,
        "product_id": PILOT_PRODUCT_ID,
        "evidence_mode": PILOT_EVIDENCE_MODE,
        "integration_mode": "SHADOW",
        "contractual": False,
        "displayable_approval": False,
    }
