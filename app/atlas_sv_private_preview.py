"""Private read-only preview of Atlas El Salvador index inside Carly.

Never installs an endpoint unless explicitly enabled. Does not write to Supabase,
modify Carly ranking, publish inventory, or imply verified stock availability.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hmac
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import Header, HTTPException, Query

ALLOWED_SOURCES=frozenset({
    "sv-easycar","sv-autospublicidad","sv-excel-usados",
    "sv-autosale","sv-julajups","sv-xautomarket",
})
PREVIEW_PATH="/internal/carly/atlas-sv-preview"
ATLAS_PATH="/internal/sv-search/search"

def _base_url() -> str:
    value=os.environ.get("CARLY_ATLAS_SV_BASE_URL","").strip().rstrip("/")
    parsed=urlparse(value)
    # Base URL is admin-controlled, not user supplied.
    if not parsed.hostname or parsed.scheme!="https" or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("","/"):
        raise HTTPException(503,"atlas_sv_preview_not_configured")
    return value

def _preview_auth(provided: str | None):
    expected=os.environ.get("CARLY_ATLAS_PREVIEW_TOKEN","")
    if len(expected)<24:
        raise HTTPException(503,"atlas_sv_preview_not_configured")
    if not provided or not hmac.compare_digest(provided,expected):
        raise HTTPException(403,"atlas_sv_preview_forbidden")

def _source_id(raw: Any) -> str:
    return str(raw or "").strip().lower()

def _url(value: Any) -> str | None:
    if not isinstance(value,str):return None
    u=urlparse(value)
    return value if u.scheme=="https" and u.hostname and not u.username and not u.password else None

def _observed_age_hours(raw: Any) -> float | None:
    if not isinstance(raw,str):return None
    try:
        dt=datetime.fromisoformat(raw.replace("Z","+00:00"))
        if dt.tzinfo is None:return None
        return round(max(0.0,(datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()/3600),1)
    except ValueError:
        return None

def _price(v: Any) -> float | None:
    try:
        x=float(v)
    except (TypeError,ValueError):
        return None
    if not 100<=x<=5_000_000:return None
    return round(x,2)

def map_vehicle(row: dict[str,Any]) -> dict[str,Any] | None:
    """Fail-closed only on core card evidence; source URL remains original."""
    if not isinstance(row,dict) or _source_id(row.get("source_id")) not in ALLOWED_SOURCES:
        return None
    if row.get("record_kind")!="vehicle_listing":return None
    make=str(row.get("make") or "").strip()[:50]
    model=str(row.get("model") or "").strip()[:90]
    try:year=int(row.get("year"))
    except (TypeError,ValueError):return None
    price=_price(row.get("price_usd"))
    original=_url(row.get("url"))
    photo=_url(row.get("photo_url"))
    if not make or not model or not 1985<=year<=2035 or price is None or not original or not photo:
        return None
    mileage=row.get("mileage_km")
    if not isinstance(mileage,int) or isinstance(mileage,bool) or not 0<=mileage<=2_000_000:
        mileage=None
    return {
        "id":str(row.get("source_id"))+":"+str(row.get("listing_key") or original),
        "source_id":row["source_id"],"country":"sv",
        "make":make,"model":model,"year":year,
        "price_usd":price,"km":mileage,
        "primary_photo":photo,"url":original,
        "transmission":str(row.get("transmission") or "")[:60] or None,
        "fuel_type":str(row.get("fuel") or "")[:60] or None,
        "location":str(row.get("seller_location") or "")[:100] or None,
        "observed_at":row.get("observed_at"),
        "age_hours":_observed_age_hours(row.get("observed_at")),
        "listing_state":"indexed_unverified",
        "requires_availability_confirmation":True,
        "status":"private_preview_only",
        "addressable":False,
    }

def atlas_sv_preview(query:str,limit:int=10,source_id:str|None=None)->dict[str,Any]:
    if not 1<=len(query.strip())<=120 or not 1<=limit<=20:
        raise HTTPException(422,"invalid_preview_request")
    if source_id is not None and source_id not in ALLOWED_SOURCES:
        raise HTTPException(422,"source_not_allowed")
    token=os.environ.get("ATLAS_SV_SEARCH_TOKEN","")
    if len(token)<24:raise HTTPException(503,"atlas_sv_preview_not_configured")
    base=_base_url()
    params={"q":query.strip(),"limit":min(100,max(limit*5,20))}
    if source_id:params["source_id"]=source_id
    try:
        with httpx.Client(timeout=httpx.Timeout(8.0,connect=3.0),follow_redirects=False) as client:
            response=client.get(base+ATLAS_PATH,params=params,headers={"Authorization":"Bearer "+token})
            response.raise_for_status()
            payload=response.json()
    except (httpx.RequestError,httpx.HTTPStatusError,ValueError) as e:
        # Hide upstream details and credentials; no fallback into Carly live data.
        raise HTTPException(502,"atlas_sv_preview_upstream_unavailable") from e
    if not isinstance(payload,dict) or payload.get("published") is not False or payload.get("staging") is not True:
        raise HTTPException(502,"atlas_sv_preview_invalid_upstream_contract")
    raw=payload.get("records")
    if not isinstance(raw,list):raise HTTPException(502,"atlas_sv_preview_invalid_upstream_contract")
    cards=[]
    for item in raw:
        c=map_vehicle(item)
        if c is not None:cards.append(c)
        if len(cards)>=limit:break
    return {
        "mode":"atlas_sv_private_preview",
        "country":"sv","query":query.strip(),"count":len(cards),
        "records":cards,
        "raw_candidates_returned":len(raw),
        "customer_facing":False,"published":False,
        "availability_verified":False,"market_coverage_verified":False,
        "carly_recommendations_modified":False,
        "disclaimer":"Historical/indexed market evidence, availability and price unverified.",
    }

def install(app:Any)->bool:
    """Opt-in only. Route must never share a public Carly search handler."""
    if os.environ.get("CARLY_ATLAS_PREVIEW_ENABLED")!="1":
        return False
    @app.get(PREVIEW_PATH)
    def preview(q:str=Query(min_length=1,max_length=120),
                limit:int=Query(default=10,ge=1,le=20),
                source_id:str|None=Query(default=None),
                x_carly_atlas_preview_token:str|None=Header(default=None)):
        _preview_auth(x_carly_atlas_preview_token)
        return atlas_sv_preview(q,limit,source_id)
    return True
