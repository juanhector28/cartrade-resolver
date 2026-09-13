from __future__ import annotations
import re, unicodedata
from dataclasses import replace
from .contracts import BuyerState, Provenance

_BRANDS={"mazda":"Mazda","toyota":"Toyota","honda":"Honda","nissan":"Nissan","ford":"Ford","kia":"Kia","hyundai":"Hyundai","mitsubishi":"Mitsubishi","audi":"Audi","bmw":"BMW","chevrolet":"Chevrolet","volkswagen":"Volkswagen","vw":"Volkswagen","jeep":"Jeep","isuzu":"Isuzu","changan":"Changan"}
_BODIES={"suv":"suv","pickup":"pickup","pick up":"pickup","sedan":"sedan","sedán":"sedan","hatchback":"hatchback"}
_NUMBER=r"[0-9]+(?:[.,][0-9]+)?"
_DAILY_KM=re.compile(rf"\b({_NUMBER})\s*(?:km|kms|kil[oó]metros?)\s*(?:diarios?|al\s+d[ií]a|por\s+d[ií]a)\b",re.I)
_MONTHLY=re.compile(rf"(?:\$\s*)?({_NUMBER})\s*(?:usd|d[oó]lares?)?\s*(?:/\s*mes|al\s+mes|por\s+mes|mensuales?|mensual)\b",re.I)
_RANGE=re.compile(rf"\b(?:entre|de)\s*(?:usd\s*)?\$?\s*({_NUMBER})\s*(?:y|a|hasta|-|–)\s*(?:usd\s*)?\$?\s*({_NUMBER})",re.I)
_FAMILY_COUNT=re.compile(r"\b(?:familia\s+de|somos|para)\s*([2-9])\b",re.I)
_YEAR_PLUS=re.compile(r"\b(20\d{2})\s*(?:\+|en\s+adelante|o\s+m[aá]s\s+nuev[oa])\b",re.I)

def _norm(text:str)->str:
    text=unicodedata.normalize("NFKD",(text or "").lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))

def _num(raw:str)->float:
    s=raw.strip().replace(" ","")
    if "," in s and "." in s: s=s.replace(",","")
    elif "," in s:
        a,b=s.rsplit(",",1); s=a.replace(".","")+("."+b if len(b)<=2 else b)
    return float(s)

def update_buyer_state(state:BuyerState,user_text:str,message_index:int)->BuyerState:
    text=user_text or ""; n=_norm(text); p=Provenance("user",message_index,text); out=state
    for alias,canonical in _BRANDS.items():
        if re.search(rf"\b{re.escape(alias)}\b",n): out=out.with_hard("make",canonical,p); break
    for token,canonical in _BODIES.items():
        if re.search(rf"\b{re.escape(_norm(token))}\b",n): out=out.with_hard("body_type",canonical,p); break
    m=_RANGE.search(text)
    if m:
        lo,hi=sorted((_num(m.group(1)),_num(m.group(2))))
        if 1000<=lo<=hi<=1_000_000: out=out.with_hard("min_price",lo,p).with_hard("max_price",hi,p)
    m=_MONTHLY.search(text)
    if m:
        v=_num(m.group(1))
        if 50<=v<=10000: out=out.with_hard("monthly_max",v,p)
    m=_DAILY_KM.search(text)
    if m:
        v=_num(m.group(1))
        if 1<=v<=2000: out=out.with_hard("daily_km",v,p)
    m=_FAMILY_COUNT.search(text)
    if m: out=out.with_hard("passengers",int(m.group(1)),p)
    m=_YEAR_PLUS.search(text)
    if m: out=out.with_hard("min_year",int(m.group(1)),p)
    use=set(out.use_cases)
    if re.search(r"\b(?:trabajo|oficina|trabajar)\b",n): use.add("work")
    if re.search(r"\b(?:hijos?|colegio|escuela|ninos?)\b",n): use.add("school_run")
    if re.search(r"\b(?:familia|familiar)\b",n): use.add("family")
    if re.search(r"\b(?:negocio|reparto|delivery|entregas)\b",n): use.add("business")
    soft=dict(out.soft)
    cues={"comfort":(r"\b(?:comodo|comoda|comodidad|confort)\b",.8),"city_maneuverability":(r"\b(?:ciudad|trafico|parquear|estacionar|urbano)\b",.8),"family_practicality":(r"\b(?:familia|familiar|hijos?|colegio|escuela)\b",.9),"fuel_economy":(r"\b(?:economico|ahorrador|gasolina|consumo)\b",.8),"cargo_space":(r"\b(?:carga|maletas|equipaje|baul)\b",.8),"performance":(r"\b(?:potencia|rapido|deportivo|performance)\b",.75),"reliability":(r"\b(?:confiable|durable|fiable)\b",.85)}
    for k,(pat,val) in cues.items():
        if re.search(pat,n): soft[k]=max(soft.get(k,0.0),val)
    if "school_run" in use:
        soft["family_practicality"]=max(soft.get("family_practicality",0.0),.9); soft["city_maneuverability"]=max(soft.get("city_maneuverability",0.0),.6)
    return replace(out,soft=soft,use_cases=frozenset(use),revision=out.revision+1)

def build_state(messages:tuple[dict[str,str],...],market:dict)->BuyerState:
    state=BuyerState(market=dict(market or {}))
    for i,m in enumerate(messages):
        if str(m.get("role","")).lower()=="user": state=update_buyer_state(state,str(m.get("content","")),i)
    return state
