"""Isolated staging app for CarTrade Deals. No financial execution authority."""
from __future__ import annotations
import os
import re
from pathlib import Path
from uuid import UUID
import httpx
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Literal
from app.deals_api import router as deals_router, _client

app = FastAPI(title="CarTrade Deals Staging", version="0.1.0")
app.include_router(deals_router)
UPSTREAM = "https://resolver.cartrade.live/carly/chat"

class ChatMsg(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2200)

class BrokerChat(BaseModel):
    messages: list[ChatMsg] = Field(min_length=1, max_length=24)
    country: Literal["sv", "gt"]
    actor_role: Literal["buyer", "seller", "broker"]
    shown_cars: list[dict] = Field(default_factory=list, max_length=8)

@app.get("/health")
def health():
    return {"status":"ok","mode":"isolated-staging","auth_configured":bool(os.getenv("SUPABASE_ANON_KEY"))}

@app.get("/api/public-config")
def public_config():
    url=os.getenv("SUPABASE_URL","")
    key=os.getenv("SUPABASE_ANON_KEY","")
    if not url or not key:
        raise HTTPException(status_code=503,detail="Staging auth is not configured")
    return {"supabaseUrl":url,"supabaseAnonKey":key,"apiBase":""}

@app.post("/api/broker/chat")
async def broker_chat(payload: BrokerChat, auth=Depends(_client)):
    # Authorization token is used locally, never forwarded to upstream.
    # Carly's existing production endpoint remains the source of real inventory.
    msgs=[m.model_dump() for m in payload.messages]
    # Safe, server-controlled context. No private Deal/customer details forwarded.
    role_context={
        "broker":"Estoy actuando como intermediario de compraventa para un cliente. Las solicitudes de búsqueda son para ese cliente, no necesariamente para mí.",
        "seller":"Estoy vendiendo un vehículo. No inventes compradores ni ofertas.",
        "buyer":"Estoy buscando un vehículo para comprar.",
    }[payload.actor_role]
    messages=[{"role":"user","content":role_context+" Mercado: "+payload.country.upper()+"."}]
    messages.extend(msgs)
    if len(messages)>24:
        messages=messages[-24:]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(110.0,connect=8.0),follow_redirects=False) as client:
            response=await client.post(UPSTREAM,json={
                "messages":messages,
                "country":payload.country,
                "top_n":4,
                "shown_cars":payload.shown_cars,
            },headers={"Accept":"application/json"})
    except httpx.TimeoutException:
        raise HTTPException(status_code=504,detail="Carly tarda más de lo esperado; intentá de nuevo.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="No fue posible conectar con Carly real.")
    if response.status_code!=200:
        raise HTTPException(status_code=502,detail="Carly real no está disponible en este momento.")
    try:
        result=response.json()
    except ValueError:
        raise HTTPException(status_code=502,detail="Respuesta inválida del servicio Carly.")
    if not isinstance(result,dict) or not isinstance(result.get("reply"),str):
        raise HTTPException(status_code=502,detail="La respuesta de Carly no tiene el formato esperado.")
    # This is only a suggestion. Explicit button confirmation POSTs /api/deals.
    last=msgs[-1]["content"] if msgs else ""
    suggestion=bool(re.search(r"\b(?:crea|crear|abre|abrir|registra|registrar)\s+(?:(?:un|el|mi)\s+)?(?:deal|expediente)\b",last,re.I))
    return {"phase":result.get("phase","conversation"),"reply":result["reply"],
            "recommendations":result.get("recommendations",[]),
            "explore":result.get("explore",[]),
            "suggest_create_deal":suggestion,
            "source":"Carly real / Atlas"}

@app.get("/api/broker/deals/{deal_id}/next-action")
def next_action(deal_id: UUID,auth=Depends(_client)):
    db,_=auth
    try:
        rows=db.table("ct_deals").select("id,status,vehicle_title,vehicle_url,market").eq("id",str(deal_id)).limit(1).execute().data or []
    except Exception:
        raise HTTPException(status_code=503,detail="No se pudo consultar el Deal")
    if not rows: raise HTTPException(status_code=404,detail="Deal no encontrado")
    deal=rows[0]
    if deal["status"]!="discovery":
        return {"action":"Consultar al equipo de operaciones","status":deal["status"],"automated":False}
    if not deal.get("vehicle_title"):
        return {"action":"Buscar opciones reales con Carly y seleccionar un vehículo","status":"discovery","automated":False}
    if not deal.get("vehicle_url"):
        return {"action":"Confirmar el anuncio y obtener su enlace verificable","status":"discovery","automated":False}
    return {"action":"Solicitar al equipo validación de disponibilidad y documentación del vendedor","status":"discovery","automated":False}

@app.get("/")
def root():
    return FileResponse(Path(__file__).parent/"index.html", media_type="text/html")
