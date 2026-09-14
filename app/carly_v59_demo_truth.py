"""Carly v59 demo-truth capsule: truth guards plus narrow retrieval recovery."""
from __future__ import annotations

import logging
import os
import re
from functools import wraps
from typing import Any

from . import main_v31 as v31
from . import main_v50 as v50
from . import carly_v52_hotfix as v52
from . import carly_v58_conversation_scope as v58

log = logging.getLogger("carly.v59")
_CONTEXT_MARKER = "[CONTEXTO ACTIVO DE CARTRADE:"
_STOPWORDS = {
    "busco","quiero","necesito","estoy","ando","buscando","un","una","el","la","de","en","y","o","con","para","por","entre","hasta",
    "usd","gt","sv","cr","pa","guatemala","salvador","costa","rica","panama","panamá","suv","pickup","pick-up","sedan","sedán",
    "hatchback","carro","auto","vehiculo","vehículo","camioneta","automatico","automático","mecanico","mecánico","manual","nuevo",
    "usado","barato","confiable","familiar","trabajo","mensual","cuota",
}
_YEARISH = re.compile(r"^(19|20)\d{2}$")
_NUMBERISH = re.compile(r"^[\d.,$]+k?$", re.I)
_COUNTRY_NAMES = {"gt":"Guatemala","sv":"El Salvador","cr":"Costa Rica","pa":"Panamá"}


def _visible_user_text(value: Any) -> str:
    text = str(value or "")
    idx = text.find(_CONTEXT_MARKER)
    if idx >= 0: text = text[:idx]
    return text.strip()


def _known_makes_normed() -> set[str]:
    out=set()
    for alias in getattr(v31,"_BRAND_ALIASES",{}) or {}: out.add(v58.v28._norm(alias))
    for alias in getattr(v58,"_BRANDS",{}) or {}: out.add(v58.v28._norm(alias))
    return out


def _unknown_make_token(text: str) -> str | None:
    if not text or not v52._SEARCH_RE.search(text): return None
    if v58._brand_in_turn(text) or v31._canonical_exact(text): return None
    known=_known_makes_normed()
    for raw in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][\w-]*",text):
        token=v58.v28._norm(raw)
        if not token or token in _STOPWORDS or token in known: continue
        if _YEARISH.match(raw) or _NUMBERISH.match(raw): continue
        if raw[:1].isupper() and len(raw)>=3: return raw
    return None


def _no_inventory_reply(token: str, country: str) -> dict[str,Any]:
    where=_COUNTRY_NAMES.get(country,"el mercado actual")
    return {"phase":"conversation","reply":f"No tengo {token} en el inventario certificado de {where} en este momento. No te voy a mostrar sustitutos como si lo fueran. Si querés, decime tu presupuesto y uso principal y te muestro alternativas reales, marcadas explícitamente como alternativas.","recommendations":[],"explore":[],"token_path":"deterministic_no_inventory_v59","route_precedence":"unknown_make_v59","llm_calls":0}


def _last_range(body: Any) -> tuple[float,float] | None:
    rng=None
    for m in v52._messages(body):
        if v52._role(m)!="user": continue
        found=v52._price_range(_visible_user_text(v52._content(m)))
        if found: rng=found
    return rng


_prior_constraints=v31._constraints

def _constraints_with_floor(body: Any,*args: Any,**kwargs: Any) -> dict[str,Any]:
    c=_prior_constraints(body,*args,**kwargs)
    try:
        rng=_last_range(body)
        if rng: c["price_min"],c["total_budget"]=rng
    except Exception: log.exception("Carly v59 price range constraint enrichment failed")
    return c

v31._constraints=_constraints_with_floor
_prior_v31_query_rows=v31._query_rows
_prior_v46_query_rows=getattr(getattr(v50,"v46",None),"_ORIG_QUERY_ROWS",None)


def _filter_price_range(rows:list[dict],c:dict[str,Any])->list[dict]:
    floor=c.get("price_min"); ceiling=c.get("total_budget") if floor is not None else None
    if floor is None: return rows
    floor=float(floor); ceiling=float(ceiling) if ceiling is not None else None; kept=[]
    for row in rows or []:
        try: price=float(row.get("price_usd"))
        except (TypeError,ValueError): continue
        if price<floor or (ceiling is not None and price>ceiling): continue
        kept.append(row)
    return kept


def _rows_with_range_v31(c:dict[str,Any],*args:Any,**kwargs:Any)->list[dict]:
    rows=_prior_v31_query_rows(c,*args,**kwargs)
    try: return _filter_price_range(rows,c)
    except Exception:
        log.exception("Carly v59 v31 range filter failed closed"); return [] if c.get("price_min") is not None else rows

v31._query_rows=_rows_with_range_v31


def _fresh_staging_fallback(c:dict[str,Any], country:str)->list[dict]:
    """Recover only fresh/indexed/addressable staging rows if v50's focused query unexpectedly returns zero."""
    client=getattr(v50.legacy,"supabase",None)
    if client is None: return []
    try:
        response=(client.table("scraped_listings").select(v31._SELECT)
                  .eq("country",country).eq("is_addressable",True)
                  .eq("listing_state","indexed")
                  .gte("last_seen_at",v50.freshness_cutoff_iso())
                  .order("updated_at",desc=True).limit(900).execute())
        broad=[dict(r) for r in (response.data or [])]
        allowed={v58.v28._norm(x) for x in (c.get("allowed_brands") or []) if str(x).strip()}
        exact=c.get("exact")
        price_cap=float(c["total_budget"]) if c.get("total_budget") is not None else None
        if c.get("monthly_max") is not None:
            implied=float(c["monthly_max"])/0.0238*1.03
            price_cap=min(price_cap,implied) if price_cap is not None else implied
        out=[]
        for row in broad:
            if v58.v28._norm(row.get("status"))!="staging": continue
            make=v58.v28._norm(row.get("make"))
            if allowed and make not in allowed: continue
            if exact and make!=v58.v28._norm(exact[0]): continue
            if c.get("min_year"):
                try:
                    if int(float(row.get("year")))<int(c["min_year"]): continue
                except (TypeError,ValueError): continue
            if c.get("require_transmission") and v31._transmission(row)!=c["require_transmission"]: continue
            if price_cap is not None:
                try:
                    if float(row.get("price_usd"))>price_cap: continue
                except (TypeError,ValueError): continue
            out.append(row)
        log.warning("CARLY_V59_SAFE_FALLBACK country=%s broad=%s kept=%s allowed=%s monthly=%s",country,len(broad),len(out),sorted(allowed),c.get("monthly_max"))
        return out
    except Exception:
        log.exception("Carly v59 fresh staging fallback failed closed")
        return []


if _prior_v46_query_rows is not None:
    def _rows_with_range_v46(c:dict[str,Any],*args:Any,**kwargs:Any)->list[dict]:
        rows=_prior_v46_query_rows(c,*args,**kwargs)
        if not rows and args:
            rows=_fresh_staging_fallback(c,str(args[0]))
        elif not rows and "country" in kwargs:
            rows=_fresh_staging_fallback(c,str(kwargs["country"]))
        try: return _filter_price_range(rows,c)
        except Exception:
            log.exception("Carly v59 v46 range filter failed closed"); return [] if c.get("price_min") is not None else rows
    v50.v46._ORIG_QUERY_ROWS=_rows_with_range_v46


def _ready_to_search(body:Any)->bool:
    try:
        c=_constraints_with_floor(body)
        has_budget=c.get("monthly_max") is not None or c.get("total_budget") is not None
        return bool(has_budget and v58._mission_known(body,c))
    except Exception: return False

_prior_opening=v52.opening_search_response
def _opening_v59(body:Any)->dict|None:
    if _ready_to_search(body): return None
    return _prior_opening(body)
v52.opening_search_response=_opening_v59


def _sanitize_user_context_inplace(body:Any)->Any:
    if body is None: return body
    msgs=v52._messages(body)
    for m in msgs:
        if v52._role(m)!="user": continue
        clean=_visible_user_text(v52._content(m))
        if isinstance(m,dict): m["content"]=clean
        else:
            try: setattr(m,"content",clean)
            except Exception: pass
    if isinstance(body,dict): body["messages"]=msgs
    else:
        try: setattr(body,"messages",msgs)
        except Exception: pass
    return body


def install(app:Any)->None:
    for route in getattr(app,"routes",[]):
        if getattr(route,"path",None)!="/carly/chat": continue
        prior=getattr(route,"endpoint",None); dependant=getattr(route,"dependant",None)
        if prior is None or dependant is None or getattr(prior,"_carly_v59_demo_truth",False): continue
        @wraps(prior)
        def endpoint(*args:Any,__prior=prior,**kwargs:Any):
            body=v58._request_body(args,kwargs); _sanitize_user_context_inplace(body)
            try:
                users=[m for m in v52._messages(body) if v52._role(m)=="user"]
                if users:
                    token=_unknown_make_token(_visible_user_text(v52._content(users[-1])))
                    if token: return _no_inventory_reply(token,v52._country(body))
            except Exception: log.exception("Carly v59 unknown-make guard failed; falling through")
            return __prior(*args,**kwargs)
        endpoint._carly_v59_demo_truth=True; endpoint._carly_v59_prior=prior; route.endpoint=endpoint; dependant.call=endpoint; break
    log.warning("CARLY_V59 installed unknown_make_guard=true price_floor=true buyer_context_isolation=true ready_search_bypass=true safe_empty_fallback=true vision_inline_max=%s vision_jit_flag=%s",os.getenv("CARLY_VISION_INLINE_MAX","(default 3)"),os.getenv("CARLY_VISION_JIT_ENABLED","(default 1 = ON)"))

_probe_unknown=_unknown_make_token("Busco un Bugatti Chiron 2025")
if not _probe_unknown or "bugatti" not in _probe_unknown.lower(): raise RuntimeError("Carly v59 unknown-make guard regression")
if _unknown_make_token("Busco un Toyota SUV") is not None: raise RuntimeError("Carly v59 Toyota false positive")
_probe_rng=v52._price_range("SUV confiable entre USD 15,000 y 25,000")
if _probe_rng!=(15000.0,25000.0): raise RuntimeError(f"Carly v59 range parse regression: {_probe_rng!r}")
_probe_ready={"country":"gt","messages":[{"role":"user","content":"Busco un SUV confiable entre USD 15,000 y 25,000 para trabajo diario"}]}
if not _ready_to_search(_probe_ready): raise RuntimeError("Carly v59 ready-search regression")
if _visible_user_text("Hola [CONTEXTO ACTIVO DE CARTRADE: radio=100km]")!="Hola": raise RuntimeError("Carly v59 context-strip regression")
