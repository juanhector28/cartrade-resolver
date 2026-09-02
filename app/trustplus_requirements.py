from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import cache

router = APIRouter(prefix="/lending", tags=["lending-requirements"])

SUPPORTED_CLAIMS = {
    "employment_status", "position", "start_date", "employment_type", "pay_frequency",
    "monthly_gross_income", "monthly_net_income", "active_oid_count",
    "monthly_oid_deductions", "other_monthly_payroll_deductions",
}
MONETARY_CLAIMS = {
    "monthly_gross_income", "monthly_net_income", "monthly_oid_deductions",
    "other_monthly_payroll_deductions",
}

TRUSTPLUS_API_BASE = os.environ.get("TRUSTPLUS_API_BASE", "").rstrip("/")
TRUSTPLUS_API_KEY = os.environ.get("TRUSTPLUS_API_KEY", "")
TRUSTPLUS_WEBHOOK_SECRET = os.environ.get("TRUSTPLUS_WEBHOOK_SECRET", "")
TRUSTPLUS_WEBHOOK_URL = os.environ.get("TRUSTPLUS_WEBHOOK_URL", "https://resolver.cartrade.live/hooks/trustplus")
TRUSTPLUS_DEMO_URL = os.environ.get("TRUSTPLUS_DEMO_URL", "")
ATLAS_REQUIREMENTS_TOKEN = os.environ.get("ATLAS_REQUIREMENTS_TOKEN", "")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@contextmanager
def _conn():
    path = os.environ.get("REQUIREMENTS_DB", cache.CACHE_DB)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA journal_mode=WAL")
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS lender_requirements (
                id TEXT PRIMARY KEY,
                application_ref TEXT NOT NULL,
                lender TEXT NOT NULL,
                claims_json TEXT NOT NULL,
                status TEXT NOT NULL,
                requested_by TEXT,
                requested_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                launch_json TEXT,
                verification_id TEXT,
                consent_url TEXT,
                result_json TEXT,
                last_error TEXT
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_lr_app ON lender_requirements(application_ref, requested_at DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_lr_verification ON lender_requirements(verification_id)")


class RequirementCreate(BaseModel):
    application_ref: str = Field(min_length=2, max_length=128)
    lender: str = Field(default="Lender", min_length=1, max_length=120)
    claims: list[str] = Field(min_length=1, max_length=20)
    requested_by: Optional[str] = Field(default=None, max_length=160)


class EmployerInput(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    contact_email: str = Field(min_length=5, max_length=254)
    domain: Optional[str] = Field(default=None, max_length=253)
    contact_source: str = "applicant_provided"


class RequirementLaunch(BaseModel):
    subject_name: str = Field(min_length=2, max_length=180)
    subject_ref: Optional[str] = Field(default=None, max_length=180)
    employer: EmployerInput
    asserted_values: dict[str, Any]
    currency: str = Field(default="USD", min_length=3, max_length=3)


def _serialize(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["claims"] = json.loads(out.pop("claims_json"))
    out["launch"] = json.loads(out.pop("launch_json")) if out.get("launch_json") else None
    out["result"] = json.loads(out.pop("result_json")) if out.get("result_json") else None
    return out


def _require_atlas_token(x_atlas_token: Optional[str]) -> None:
    if not ATLAS_REQUIREMENTS_TOKEN:
        raise HTTPException(503, "Atlas requirement bridge is not configured")
    if not (x_atlas_token and secrets.compare_digest(x_atlas_token, ATLAS_REQUIREMENTS_TOKEN)):
        raise HTTPException(401, "invalid Atlas requirements token")


@router.post("/requirements")
def create_requirement(body: RequirementCreate, x_atlas_token: str | None = Header(None)):
    _require_atlas_token(x_atlas_token)
    claims, seen = [], set()
    for claim in body.claims:
        claim = str(claim).strip()
        if claim not in SUPPORTED_CLAIMS:
            raise HTTPException(422, f"unsupported claim: {claim}")
        if claim not in seen:
            seen.add(claim); claims.append(claim)
    rid, at = "req_" + secrets.token_hex(6), _now()
    with _conn() as con:
        con.execute("""INSERT INTO lender_requirements
            (id,application_ref,lender,claims_json,status,requested_by,requested_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (rid, body.application_ref.strip(), body.lender.strip(), json.dumps(claims),
             "awaiting_customer", body.requested_by, at, at))
        row = con.execute("SELECT * FROM lender_requirements WHERE id=?", (rid,)).fetchone()
    return _serialize(row)


@router.get("/requirements")
def list_requirements(application_ref: str | None = None, limit: int = 20):
    limit = max(1, min(100, int(limit)))
    with _conn() as con:
        if application_ref:
            rows = con.execute("SELECT * FROM lender_requirements WHERE application_ref=? ORDER BY requested_at DESC LIMIT ?", (application_ref, limit)).fetchall()
        else:
            rows = con.execute("SELECT * FROM lender_requirements ORDER BY requested_at DESC LIMIT ?", (limit,)).fetchall()
    return {"requirements": [_serialize(r) for r in rows]}


@router.get("/requirements/{requirement_id}")
def get_requirement(requirement_id: str):
    with _conn() as con:
        row = con.execute("SELECT * FROM lender_requirements WHERE id=?", (requirement_id,)).fetchone()
    if not row:
        raise HTTPException(404, "requirement not found")
    return _serialize(row)


def _claim_payload(claim: str, value: Any, currency: str) -> dict:
    item = {"claim": claim, "asserted_value": value}
    if claim in MONETARY_CLAIMS:
        item["currency"] = currency.upper()
    return item


@router.post("/requirements/{requirement_id}/launch")
def launch_requirement(requirement_id: str, body: RequirementLaunch):
    with _conn() as con:
        row = con.execute("SELECT * FROM lender_requirements WHERE id=?", (requirement_id,)).fetchone()
        if not row:
            raise HTTPException(404, "requirement not found")
        claims = json.loads(row["claims_json"])

    missing = [c for c in claims if body.asserted_values.get(c) in (None, "")]
    if missing:
        raise HTTPException(422, {"message": "missing asserted values", "claims": missing})

    launch = body.model_dump(); launch["currency"] = body.currency.upper()
    payload = {
        "requester": "Atlas Capital",
        "purpose": "credit_underwriting",
        "subject_name": body.subject_name,
        "subject_ref": body.subject_ref or row["application_ref"],
        "employer": body.employer.model_dump(),
        "claims": [_claim_payload(c, body.asserted_values[c], body.currency) for c in claims],
        "webhook_url": TRUSTPLUS_WEBHOOK_URL,
    }

    verification_id = consent_url = None
    status, last_error = "awaiting_consent", None
    if TRUSTPLUS_API_BASE and TRUSTPLUS_API_KEY:
        idem = f"atlas-{row['application_ref']}-{requirement_id}"
        try:
            with httpx.Client(timeout=12.0) as client:
                resp = client.post(f"{TRUSTPLUS_API_BASE}/v1/verifications",
                    headers={"X-API-Key": TRUSTPLUS_API_KEY, "Idempotency-Key": idem}, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(f"Trust+ HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            verification_id, consent_url = data.get("verification_id"), data.get("consent_url")
            status = data.get("status") or status
        except Exception as exc:
            status, last_error = "launch_error", str(exc)[:500]
    elif TRUSTPLUS_DEMO_URL:
        consent_url, status = TRUSTPLUS_DEMO_URL, "awaiting_consent"
    else:
        status, last_error = "ready_to_launch", "Trust+ transport is not configured"

    at = _now()
    with _conn() as con:
        con.execute("""UPDATE lender_requirements SET status=?,updated_at=?,launch_json=?,verification_id=?,consent_url=?,last_error=? WHERE id=?""",
                    (status, at, json.dumps(launch), verification_id, consent_url, last_error, requirement_id))
        updated = con.execute("SELECT * FROM lender_requirements WHERE id=?", (requirement_id,)).fetchone()
    return _serialize(updated)


async def trustplus_webhook(request: Request):
    raw = await request.body()
    if not TRUSTPLUS_WEBHOOK_SECRET:
        raise HTTPException(503, "Trust+ webhook verification is not configured")
    signature = request.headers.get("X-Trustplus-Signature", "")
    expected = hmac.new(TRUSTPLUS_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "invalid Trust+ signature")
    try:
        event = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid JSON")
    vid = event.get("verification_id")
    if not vid:
        raise HTTPException(422, "verification_id is required")
    name = str(event.get("event") or "")
    status_map = {"consent.granted":"employer_pending","verification.completed":"completed","verification.expired":"expired"}
    new_status, at = status_map.get(name, name or "updated"), _now()
    with _conn() as con:
        row = con.execute("SELECT * FROM lender_requirements WHERE verification_id=? ORDER BY requested_at DESC LIMIT 1", (vid,)).fetchone()
        if not row:
            return {"ok": True, "matched": False}
        result = json.dumps(event) if name in {"verification.completed", "verification.expired"} else row["result_json"]
        con.execute("UPDATE lender_requirements SET status=?,updated_at=?,result_json=?,last_error=NULL WHERE id=?", (new_status, at, result, row["id"]))
    return {"ok": True, "matched": True, "requirement_id": row["id"]}
