"""Isolated Carly Paste the Link staging (one validated public source).

Runs with: uvicorn app.paste_link_staging:app --host 0.0.0.0 --port $PORT
Does not import production main, create Supabase clients, cache links,
or publish any source content to an inventory.
"""
from __future__ import annotations

import ipaddress
import time
from collections import defaultdict, deque
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import platforms
from .social_search import router as social_search_router
from .social_intake import social_platform, capture_reference
from .paste_link_source_registry import SOURCES, public_status, source_for_url
from .paste_link_readiness import get_readiness
from .resolvers import fallback

app = FastAPI(title="Carly · Pega el link · Staging", docs_url=None, redoc_url=None)
app.include_router(social_search_router)
SOURCE_HOST = "carroselsalvador.com"
AGENT = "CarTrade-Link-Diagnostic/0.1"
WINDOW = 3600
MAX_PER_IP = 12
_limits: dict[str, deque] = defaultdict(deque)


class ResolveBody(BaseModel):
    url: str
    country: str | None = None


def is_pilot_listing(url: str) -> bool:
    """True for an individual listing route in an explicitly enabled stage source."""
    return source_for_url(url) is not None



def rate_check(ip: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        ip = "unrecognized"
    queue = _limits[ip]
    while queue and queue[0] <= now - WINDOW:
        queue.popleft()
    if len(queue) >= MAX_PER_IP:
        return False
    queue.append(now)
    return True


async def robots_allows(url: str) -> bool:
    # Hosts are prevalidated to a fixed literal hostname: no arbitrary SSRF.
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    async with httpx.AsyncClient(timeout=8, follow_redirects=False,
                                  headers={"User-Agent": AGENT}) as cli:
        response = await cli.get(robots_url)
    if response.status_code == 404:
        return True
    if response.status_code != 200:
        return False
    robots = RobotFileParser()
    robots.parse(response.text.splitlines())
    return robots.can_fetch(AGENT, url)


@app.get("/health")
def health():
    return {"ok": True, "environment": "staging", "source": SOURCE_HOST,
            "sources_enabled": sum(x["enabled"] for x in public_status()),
            "storage": False, "production": False}


@app.get("/api/sources")
def sources():
    return {"sources": public_status(), "storage": False, "environment": "staging"}

@app.get("/api/coverage")
def coverage():
    """Static committed QA receipts, not live checks or production clearance."""
    return get_readiness()


@app.post("/api/resolve")
async def resolve(body: ResolveBody, request: Request, response: Response):
    # Asking prices are source observations and must never be cached by clients.
    response.headers["Cache-Control"] = "no-store, max-age=0"
    url = body.url.strip()
    if social_platform(url):
        ip = request.client.host if request.client else "unrecognized"
        if not rate_check(ip):
            raise HTTPException(429, "Límite de pruebas por hora alcanzado.")
        return await capture_reference(url, body.country)
    source = source_for_url(url)
    if not source:
        raise HTTPException(status_code=400, detail="Enlace no habilitado o no corresponde a un anuncio individual de una fuente en pruebas.")
    source_host, source_data = source
    ip = request.client.host if request.client else "unrecognized"
    if not rate_check(ip):
        raise HTTPException(status_code=429, detail="Límite de pruebas por hora alcanzado.")
    try:
        if not await robots_allows(url):
            raise HTTPException(
                status_code=403,
                detail=(f"{source_data['name']}: no podemos confirmar que la fuente "
                        "permita esta consulta automatizada desde staging. "
                        "No intentaremos evitar sus restricciones."),
            )
        listing = await fallback.resolve(url)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="No se pudo acceder a la fuente.")
    if listing.errors:
        raise HTTPException(status_code=502, detail="La fuente no devolvió una ficha utilizable.")
    def val(field):
        item = getattr(listing, field, None)
        return item.value if item is not None else None
    # Deliberately not persisted, and no inventory lookup.
    photos = [
        photo for photo in listing.photos[:3]
        if isinstance(photo, str) and urlparse(photo).scheme == "https"
        and bool(urlparse(photo).hostname)
    ]
    if not val("title") or not val("price_usd"):
        if source_host == "julajups.sv":
            message = ("Julajups: no se pudo confirmar el precio de este anuncio específico. "
                       "No mostraremos un precio supuesto. Comparte el enlace para revisar su estructura.")
        elif source_host == "easycar.com.sv":
            message = ("EasyCar: el anuncio carga los datos con JavaScript y el extractor "
                       "todavía no puede comprobar su precio. Integración pendiente.")
        elif source_host == "crediq.com":
            message = ("CrediQ: el precio del anuncio no pudo verificarse y la fuente "
                       "requiere revisión de acceso. No se inventarán datos.")
        else:
            message = ("No se pudo verificar el precio de este anuncio. "
                       "Puede tener una estructura distinta o no estar disponible.")
        raise HTTPException(status_code=422, detail=message)
    return {
        "environment": "staging", "pilot_readonly": True, "saved": False,
        "source": source_host, "source_stage": source_data["stage"], "source_url": url,
        "title": val("title"), "price_usd": val("price_usd"),
        "year": val("year"), "km": val("km"),
        "photos": photos, "photo_url_verified": False,
        "extracted_at": listing.scraped_at,
    }


STAGING_PAGE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Carly · Pega el link · Staging</title>
<style>
:root{color-scheme:light;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#252e2b;background:#f8faf9}
*{box-sizing:border-box}body{margin:0}.shell{max-width:880px;margin:0 auto;padding:36px 22px 100px}
.header{display:flex;justify-content:space-between;align-items:center;padding-bottom:38px}.brand{font-weight:750;letter-spacing:-1.2px;font-size:25px}.tag{color:#3a6556;background:#e6f3ed;padding:7px 11px;border-radius:99px;font-size:12px;font-weight:650}
h1{font-size:clamp(36px,6vw,56px);letter-spacing:-2.5px;line-height:1.08;margin:36px 0 14px}
.sub{font-size:17px;color:#737f78;line-height:1.5;max-width:630px}.form{display:flex;gap:10px;background:#fff;padding:8px;border:1px solid #dae1dc;border-radius:16px;margin:30px 0 10px;box-shadow:0 14px 36px #1a3e2c0a}
input{border:0;outline:0;min-width:0;flex:1;padding:13px;font-size:15px}button{background:#296b50;color:white;font-size:15px;font-weight:650;border:0;border-radius:11px;padding:15px 22px;cursor:pointer}button:disabled{opacity:.55;cursor:wait}
.note{font-size:13px;color:#849088;line-height:1.5}
.sources{display:flex;gap:7px;flex-wrap:wrap;margin:14px 0}.coverage{font-size:13px;color:#315e4b;background:#e8f2ec;border:1px solid #d1e4d7;padding:12px 15px;border-radius:12px;margin:15px 0 10px;line-height:1.5}
.source-chip{font-size:12px;background:#e8f2eb;border:1px solid #cde2d4;padding:6px 10px;border-radius:99px;color:#34604a}
.source-chip.experimental{background:#f3f4f3;border-color:#e4e7e3;color:#627168}.source-chip.pending{background:#f8f4eb;border-color:#ece1c9;color:#836338}.status{margin-top:23px;color:#526c5b;font-size:14px;min-height:24px}.error{color:#a13d3d}
.card{display:none;margin-top:25px;overflow:hidden;background:#fff;border:1px solid #e0e6e2;border-radius:20px;box-shadow:0 20px 50px #192c220d}.image{height:330px;background:#edf4ef;display:flex;justify-content:center;align-items:center;position:relative;color:#76857c}.image img{width:100%;height:100%;object-fit:contain;display:none}.content{padding:28px}.meta{font-size:13px;color:#88978e;text-transform:uppercase;letter-spacing:1.2px}.car{font-size:27px;font-weight:730;letter-spacing:-.8px;margin:9px 0}.price{font-size:37px;letter-spacing:-1.5px;font-weight:760;color:#225f48;margin:11px 0 20px}.details{display:flex;gap:12px;flex-wrap:wrap}.detail{background:#f2f6f3;border-radius:8px;padding:10px 14px;color:#415449;font-size:14px}.source{display:inline-block;margin-top:22px;font-size:14px;color:#296b50}.photo-status{margin-top:10px;font-size:12px;color:#79877e}
@media(max-width:600px){.shell{padding:22px 16px 60px}.header{padding-bottom:12px}.form{flex-direction:column}h1{letter-spacing:-1.6px}.image{height:240px}}
</style>
</head>
<body><div class="shell"><header class="header"><div class="brand">carly<span style="color:#42896b">.</span></div><div class="tag">Entorno de pruebas</div></header>
<h1>¿Ya viste un carro?<br>Pega el link.</h1>
<p class="sub">Probamos la extracción automática de precio, fotografía y características de anuncios de <strong>sitios participantes en nuestro entorno de pruebas</strong>. Los enlaces sociales se reciben como candidatos pendientes de revisión.</p>
<form class="form" id="form"><input id="url" aria-label="URL del anuncio" type="url" required placeholder="Pega el enlace de un vehículo..." autocomplete="url">
<select id="country" aria-label="País del vehículo"><option value="SV">El Salvador</option><option value="GT">Guatemala</option></select>
<button id="send" type="submit">Continuar</button></form>
<p class="note">Entorno multisitio: cada fuente tiene reglas individuales. Una muestra exitosa no certifica todos los anuncios ni autoriza reutilizar contenido. La fotografía se verifica directamente en tu navegador.</p>
<div id="coverage" class="coverage" aria-live="polite">Verificando el registro de pruebas…</div>
<div id="sources" class="sources" aria-label="Fuentes en pruebas"></div>
<section aria-label="Buscar publicaciones sociales"><h2>Publicaciones sociales</h2><form id="social-search-form" class="form"><input id="social-query" aria-label="Marca, modelo o año" required placeholder="Ej. Honda"><button type="submit">Buscar</button></form><p id="social-search-status" role="status"></p><div id="social-search-results"></div></section>
<div id="status" class="status" aria-live="polite"></div>
<section id="card" class="card"><div class="image"><span id="placeholder">Esperando fotografía…</span><img id="photo" alt="Fotografía del vehículo"></div>
<div class="content"><div class="meta">Ficha recuperada de la fuente</div><div class="car" id="title"></div><div class="price" id="price"></div>
<div class="details"><span class="detail" id="year"></span><span class="detail" id="km"></span></div><div id="photo-status" class="photo-status"></div>
<a class="source" id="source" target="_blank" rel="noopener noreferrer">Ver publicación original ↗</a></div></section></div>
<script>
const $=id=>document.getElementById(id);
$("social-search-form").addEventListener("submit",async event=>{
 event.preventDefault();const button=event.currentTarget.querySelector("button");button.disabled=true;
 $("social-search-results").replaceChildren();$("social-search-status").textContent="Buscando publicaciones…";
 try{
  const params=new URLSearchParams({q:$("social-query").value,country:$("country").value});
  const reply=await fetch("/carly/social-search?"+params);
  const data=await reply.json();if(!reply.ok)throw new Error(data.detail||"No se pudo buscar");
  if(data.social_status!=="ok")throw new Error("La búsqueda social no está disponible temporalmente.");
  $("social-search-status").textContent=data.count?data.count+" publicaciones pendientes de verificar":"No encontramos publicaciones con datos suficientes para esta búsqueda.";
  for(const candidate of data.social_candidates){
   const box=document.createElement("article");box.style.cssText="background:white;padding:18px;margin:10px 0;border:1px solid #dae1dc;border-radius:12px";
   const title=document.createElement("strong");title.textContent=[candidate.make,candidate.model,candidate.year].filter(Boolean).join(" ");
   const note=document.createElement("p");note.textContent=candidate.label+" · "+candidate.platform;
   const link=document.createElement("a");link.href=candidate.url;link.target="_blank";link.rel="noopener noreferrer";link.textContent="Ver publicación original";
   box.append(title,note,link);$("social-search-results").append(box);
  }
 }catch(error){$("social-search-status").textContent=error.message}
 finally{button.disabled=false}
});
fetch("/api/coverage").then(r=>r.json()).then(d=>{
 const count=Number(d.pilot_candidates||0);
 const samples=Number(d.core_field_samples_verified||0);
 $("coverage").textContent=count+" fuentes con muestras probadas · "+samples+
  " fichas con campos básicos verificados · Sin activación en producción";
}).catch(()=>{$("coverage").textContent="Registro de cobertura temporalmente no disponible";});

fetch("/api/sources").then(r=>r.json()).then(d=>{
 (d.sources||[]).filter(x=>x.enabled).forEach(x=>{
  const chip=document.createElement("span");
  const verified=x.stage==="browser_sample_verified"||x.stage==="browser_verified";
  const pending=x.stage==="javascript_required"||x.stage==="access_review";
  chip.className="source-chip"+(pending?" pending":verified?"":" experimental");
  const suffix=verified?" · muestra probada":x.stage==="javascript_required"?" · integración JS pendiente":x.stage==="access_review"?" · acceso pendiente":" · experimental";
  chip.textContent=x.name+suffix;
  $("sources").appendChild(chip);
 });
}).catch(()=>{});

$("url").value="https://www.carroselsalvador.com/anuncios/kia-sportage-2006/";
$("form").addEventListener("submit",async e=>{
 e.preventDefault();$("send").disabled=true;$("card").style.display="none";
 $("status").className="status";$("status").textContent="Consultando el anuncio…";
 try{
  const r=await fetch("/api/resolve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:$("url").value,country:$("country").value})});
  const d=await r.json();
  if(!r.ok)throw new Error(d.detail||"No se pudo recuperar el anuncio");
  if(d.candidate_saved === true && typeof d.candidate_id === "string" && d.candidate_id){
   $("status").textContent="Recibimos el enlace. Nos encargamos del resto.";
   const c=d.vehicle_card;
   if(c && c.fields && Object.keys(c.fields).length){
    const f=c.fields,v=k=>f[k]&&f[k].value;
    $("title").textContent=[v("make"),v("model"),v("year")].filter(Boolean).join(" ")||"Publicación recibida";
    $("price").textContent=v("price")!=null&&v("currency")?Number(v("price")).toLocaleString("es",{style:"currency",currency:v("currency")}):"Precio pendiente";
    $("year").textContent=v("year")?"Año · "+v("year"):"Año pendiente";
    $("km").textContent=v("km")!=null?Number(v("km")).toLocaleString("es")+" km":"Kilometraje pendiente";
    document.querySelector("#card .meta").textContent="Datos de la publicación · Pendientes de verificar";
    $("source").href=d.source_url;
    $("photo").style.display="none";$("photo").removeAttribute("src");
    $("placeholder").style.display="block";$("placeholder").textContent="Fotografía pendiente";
    $("photo-status").textContent="Disponibilidad pendiente de confirmar";
    $("card").style.display="block";
    $("status").textContent="Recibimos el enlace. Ficha preliminar lista para revisión.";
    if(c.photos && c.photos[0]){
     const preview=new Image();preview.referrerPolicy="no-referrer";
     preview.onload=()=>{$("photo").src=preview.src;$("photo").style.display="block";$("placeholder").style.display="none";$("photo-status").textContent="Portada del video · No confirma condición ni disponibilidad"};
     preview.onerror=()=>{$("placeholder").textContent="Portada no disponible"};
     preview.src=c.photos[0];
    }
   }
   return;
  }
  if(d.status === "pending_review")throw new Error("No se pudo confirmar la recepción del enlace.");
  $("title").textContent=d.title;
  $("price").textContent=Number(d.price_usd).toLocaleString("en-US",{style:"currency",currency:"USD",maximumFractionDigits:0});
  $("year").textContent=d.year?"Año · "+d.year:"Año no disponible";
  $("km").textContent=d.km!=null?Number(d.km).toLocaleString("en-US")+" km":"Kilometraje no disponible";
  $("source").href=d.source_url;
  $("photo").style.display="none";$("photo").removeAttribute("src");
  $("placeholder").style.display="block";$("placeholder").textContent="Verificando fotografía…";
  $("photo-status").textContent="La imagen aún no se ha verificado visualmente";
  $("card").style.display="block";$("status").textContent="Ficha recuperada. Verificando que la foto cargue…";
  if(d.photos&&d.photos[0]){
   const img=new Image();img.referrerPolicy="no-referrer";
   img.onload=()=>{$("photo").src=img.src;$("photo").style.display="block";$("placeholder").style.display="none";$("photo-status").textContent="Fotografía cargada correctamente en este navegador";$("status").textContent="Título, precio y ficha recuperados."};
   img.onerror=()=>{$("placeholder").textContent="La imagen de origen no se pudo cargar";$("photo-status").textContent="URL recuperada, pero carga visual fallida";$("status").textContent="Ficha recuperada; fotografía pendiente de corregir."};
   img.src=d.photos[0];
  }else{$("placeholder").textContent="No se encontró fotografía";$("status").textContent="Ficha recuperada sin fotografía."}
 }catch(err){$("status").className="status error";$("status").textContent=err.message}
 finally{$("send").disabled=false}
});
</script></body></html>"""


from .paste_link_manual_fallback import attach_manual_fallback

STAGING_PAGE = attach_manual_fallback(STAGING_PAGE)


@app.get("/ops/solicitudes", response_class=HTMLResponse)
def buyer_ops_demo():
    # Fictitious records only, never connects to Supabase or real operator tokens.
    from .buyer_ops_demo import demo_response
    return demo_response()


@app.get("/", response_class=HTMLResponse)
def home():
    return STAGING_PAGE

