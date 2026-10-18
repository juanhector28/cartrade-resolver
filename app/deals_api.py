"""Authenticated, owner-scoped draft Deal API. No financial approvals or closing writes."""
from typing import Optional, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from supabase import create_client
import os

router = APIRouter(prefix="/api/deals", tags=["Deals"])

class NewDeal(BaseModel):
    market: Literal["gt", "sv"]
    actor_role: Literal["buyer", "seller", "broker"]
    buyer_label: Optional[str] = Field(default=None, max_length=120)
    vehicle_title: Optional[str] = Field(default=None, max_length=160)
    vehicle_url: Optional[str] = Field(default=None, max_length=2048)
    asking_price_usd: Optional[float] = Field(default=None, ge=0, le=100000000)

def _client(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    url = os.getenv("SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY")
    if not url or not anon_key:
        raise HTTPException(status_code=503, detail="Deals authentication not configured")
    client = create_client(url, anon_key)
    try:
        user = client.auth.get_user(token).user
        if not user:
            raise ValueError("missing user")
        # REST requests execute as the authenticated user so RLS applies.
        client.postgrest.auth(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid session")
    return client, str(user.id)

@router.get("")
def list_deals(auth=Depends(_client)):
    db, _ = auth
    try:
        response = db.table("ct_deals").select("*").order("created_at", desc=True).limit(100).execute()
        return {"deals": response.data or []}
    except Exception:
        raise HTTPException(status_code=503, detail="Deals storage unavailable")

@router.post("", status_code=201)
def create_deal(payload: NewDeal, auth=Depends(_client)):
    db, uid = auth
    row = payload.model_dump(exclude_none=True)
    row.update({"created_by": uid, "status": "discovery"})
    try:
        response = db.table("ct_deals").insert(row).execute()
        if not response.data:
            raise RuntimeError("No row returned")
        return {"deal": response.data[0]}
    except Exception:
        raise HTTPException(status_code=503, detail="Deal could not be created")

@router.get("/{deal_id}")
def get_deal(deal_id: UUID, auth=Depends(_client)):
    db, _ = auth
    try:
        rows = db.table("ct_deals").select("*").eq("id",str(deal_id)).limit(1).execute().data or []
    except Exception:
        raise HTTPException(status_code=503, detail="Deals storage unavailable")
    if not rows:
        raise HTTPException(status_code=404, detail="Deal not found")
    return {"deal": rows[0]}
