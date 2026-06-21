"""CarTrade link resolver — FastAPI entry point.

POST /resolve-link
POST /inventory-run
POST /inventory-run/crautos
GET  /inventory-preview
POST /carly/search        (added) Carly: NL car search over real inventory
GET  /stats               (added) inventory-domination metrics
GET  /health
"""
from __future__ import annotations

import os
import re
import time
import random
import asyncio
import sqlite3
import logging
import httpx
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, HttpUrl
from selectolax.parser import HTMLParser
from supabase import create_client

from . import cache, rate_limit, platforms
from .resolvers import encuentra24, olx, facebook, mercadolibre, fallback
from .resolvers.base import Listing

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("resolver")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else None

# Auto-save every NEW valid link consulted via /resolve-link (dedup by URL is automatic).
# Set AUTO_SAVE_LINKS=0 to disable and revert to explicit save-only behavior.
AUTO_SAVE_LINKS = os.environ.get("AUTO_SAVE_LINKS", "1") != "0"

COUNTRY_SEARCH_URLS = {
    "sv": "https://www.encuentra24.com/el-salvador-es/autos-usados",
    "gt": "https://www.encuentra24.com/guatemala-es/autos-usados",
    "cr": "https://www.encuentra24.com/costa-rica-es/autos-usados",
    "pa": "https://www.encuentra24.com/panama-es/autos-usados",
    "hn": "https://www.encuentra24.com/honduras-es/autos-usados",
    "ni": "https://www.encuentra24.com/nicaragua-es/autos-usados",
}

_health = {
    "encuentra24": {"last_ok": None, "last_error": None, "last_at": None},
    "olx": {"last_ok": None, "last_error": None, "last_at": None},
    "facebook": {"last_ok": None, "last_error": None, "last_at": None},
    "mercadolibre": {"last_ok": None, "last_error": None, "last_at": None},
}


def _record(platform: str, ok: bool, error: Optional[str] = None):
    h = _health.get(platform)
    if h:
        h["last_at"] = int(time.time())
        if ok:
            h["last_ok"] = int(time.time())
            h["last_error"] = None
        else:
            h["last_error"] = error


def field_value(payload: dict, key: str):
    v = payload.get(key)
    if isinstance(v, dict):
        return v.get("value")
    return v


def listing_id(url: str | None):
    m = re.search(r"/(\d{6,9})/?$", (url or "").rstrip("/"))
    return m.group(1) if m else None


def photo_id(url: str):
    m = re.search(r"/(\d{6,9})_", url)
    return m.group(1) if m else None


def photo_key(url: str):
    return url.rstrip("/").split("/")[-1]


def to_large_photo(url: str):
    return re.sub(r"/t_or_fh_\w+/", "/t_or_fh_l/", url)


def to_medium_photo(url: str):
    return re.sub(r"/t_or_fh_\w+/", "/t_or_fh_m/", url)


def clean_photos(photos: list, source_url: str):
    lid = listing_id(source_url)
    cleaned = []
    seen = set()

    for raw_url in photos or []:
        if not isinstance(raw_url, str):
            continue

        url = raw_url.strip().rstrip("\\").strip()

        if not url.startswith("http"):
            continue

        if url.endswith("/"):
            continue

        segment = url.rstrip("/").split("/")[-1]

        # complete filename = listingid_hash or listingid_hash-suffix
        if not re.match(r"^\d{6,9}_[0-9a-f]{6,}(-[0-9a-f]{4,})?$", segment):
            continue

        # prevent cross-listing photo contamination
        if lid and photo_id(url) != lid:
            continue

        key = photo_key(url)
        if key in seen:
            continue

        seen.add(key)
        cleaned.append(to_large_photo(url))

    return cleaned[:8]


def infer_fuel_from_text(text: str | None):
    if not text:
        return None

    t = text.lower()

    if "diesel" in t:
        return "Diesel"
    if "gasolina" in t:
        return "Gasolina"
    if "híbrido" in t or "hibrido" in t or "hybrid" in t:
        return "Híbrido"
    if "eléctrico" in t or "electrico" in t or "electric" in t:
        return "Eléctrico"

    return None


def infer_transmission_from_text(text: str | None):
    if not text:
        return None

    t = text.lower()

    if "manual" in t:
        return "Manual"
    if "automático" in t or "automatica" in t or "automática" in t or "automatico" in t or "automatic" in t:
        return "Automática"

    return None


def normalize_fuel(value: str | None):
    if not value:
        return None

    t = value.strip().lower()

    if t == "diesel":
        return "Diesel"
    if t == "gasolina":
        return "Gasolina"
    if t in {"híbrido", "hibrido", "hybrid"}:
        return "Híbrido"
    if t in {"eléctrico", "electrico", "electric"}:
        return "Eléctrico"

    return None


def normalize_transmission(value: str | None):
    if not value:
        return None

    t = value.strip().lower()

    if t.startswith("manual"):
        return "Manual"
    if t.startswith("autom") or t == "automatic":
        return "Automática"

    return None


# ============================================================================
# ENRICHMENT (added) — body_type + quality_score, populated at scrape time so
# new rows are immediately addressable and searchable by Carly.
# Mirrors the one-time SQL enrichment we ran on the existing 5,879 rows.
# ============================================================================
_SUV = {
    "tucson", "rav4", "cr-v", "crv", "sportage", "santa fe", "santafe", "pilot", "cx-5", "cx5",
    "range rover", "outlander", "outlander sport", "qashqai", "explorer", "hr-v", "hrv", "kicks",
    "creta", "vitara", "grand vitara", "sorento", "edge", "rogue", "rogue sport", "escape", "trax",
    "tracker", "grand cherokee", "cherokee", "x-trail", "xtrail", "montero sport", "montero",
    "montero gls", "pajero", "levante", "compass", "renegade", "soul", "4runner", "land cruiser",
    "landcruiser", "e-tron", "etron", "wrangler", "tiguan", "t-cross", "tcross", "taos", "seltos",
    "stonic", "captiva", "equinox", "kona", "palisade", "telluride", "macan", "cayenne", "bronco",
    "bronco sport", "expedition", "tahoe", "suburban", "highlander", "sequoia", "fortuner", "terios",
    "raize", "corolla cross", "c-hr", "chr", "eclipse cross", "captur", "duster", "koleos", "haval",
    "jolion", "territory", "eclipse", "asx", "crosstrek", "forester", "outback", "xc40", "xc60",
    "xc90", "tiggo", "ux", "murano", "pathfinder", "armada", "juke", "ecosport", "venue", "xv",
    "santa cruz", "defender", "discovery", "discovery sport", "velar", "evoque", "urus", "bentayga",
    "gv70", "gv80", "zr-v", "zrv", "wr-v", "wrv", "rush", "prado", "mdx", "rdx", "everest",
    "coolray", "mustang", "camaro", "rexton", "gs8", "f-pace", "tivoli", "sonet", "3008", "5008",
    "jimny", "azkarra", "gx3", "veloster", "cooper", "mini", "h6", "x-terra", "xterra",
    "trailblazer", "blazer", "traverse", "acadia", "enclave", "terrain", "encore", "cx-30", "cx-3",
    "cx-9", "cx-50", "cx-90",
}
_PICKUP = {
    "hilux", "frontier", "ranger", "tacoma", "d-max", "dmax", "f-150", "f150", "l200", "np300",
    "ridgeline", "colorado", "tundra", "titan", "gladiator", "dakota", "hardbody", "bt-50", "bt50",
    "amarok", "sierra", "silverado", "ram", "ram 1500", "dongfeng rich", "terraking", "navara",
    "triton", "glory 500", "sail", "wingle", "alaskan", "maverick", "f-250", "f250", "raptor",
    "k2700", "hi-lux",
}
_HATCH = {
    "yaris", "rio", "picanto", "spark", "march", "swift", "i10", "grand i10", "grand i-10", "fit",
    "gol", "polo", "fiesta", "mazda2", "mazda 2", "demio", "sonic", "beat", "mirage", "up", "kwid",
    "agya", "morning", "i20", "fabia", "clio", "sandero", "aygo", "308", "208", "118i", "116i",
    "120i", "a1", "golf", "jazz", "note", "vios", "brio", "ignis", "celerio", "alto", "wagon r",
    "splash", "onix", "ka", "figo", "aveo", "c3", "echo", "k3",
}
_VAN = {
    "odyssey", "sienna", "caravan", "grand caravan", "hiace", "hi-ace", "urvan", "transit", "h1",
    "h-1", "starex", "carnival", "sedona", "town & country", "quest", "previa", "vellfire", "alphard",
    "voyager", "noah", "voxy", "serena", "staria", "carens", "xpander", "ertiga", "spin", "livina",
    "t2", "k2500",
}
_SEDAN = {
    "accent", "corolla", "elantra", "civic", "sentra", "versa", "soluto", "jetta", "sonata", "camry",
    "altima", "optima", "k5", "forte", "cerato", "lancer", "attrage", "city", "virtus", "logan",
    "passat", "accord", "legacy", "mirage g4", "almera", "sunny", "sylphy", "ioniq", "model 3",
    "model s", "impreza", "wrx", "mazda3", "mazda 3", "mazda6", "mazda 6", "focus", "cruze", "prius",
    "corsa", "vento", "grand siena", "siena", "verna", "sedan", "a3", "a4", "a5", "a6", "328i",
}


def _family_body(m: str) -> Optional[str]:
    """Body type by luxury model family / trim prefix (handles trims like gle450, rx 450h)."""
    if re.match(r"^x[1-7]\b", m):
        return "suv"
    if re.match(r"^q[2-8]\b", m):
        return "suv"
    if re.match(r"^qx\d", m):
        return "suv"
    if re.match(r"^(gle|glc|gla|glb|gls|gl|eqb|eqc|g-class|gv)\b", m):
        return "suv"
    if re.match(r"^(rx|nx|ux|gx|lx|rz)\b", m):
        return "suv"
    if re.match(r"^cx-?\d", m):
        return "suv"
    if "range rover" in m:
        return "suv"
    if re.match(r"^(c|e|s|cla|cls)-?class\b", m) or re.match(r"^[ces]\d{3}\b", m):
        return "sedan"
    if re.match(r"^a-?class\b", m):
        return "hatch"
    if re.match(r"^\d series\b", m) or re.match(r"^\d{3}i\b", m):
        return "sedan"
    return None


def classify_body_type(model: str | None, title: str | None) -> str:
    m = (model or "").strip().lower()
    t = (title or "").lower()
    fam = _family_body(m)
    if fam:
        return fam
    if m in _PICKUP:
        return "pickup"
    if m in _SUV:
        return "suv"
    if m in _VAN:
        return "van"
    if m in _HATCH:
        return "hatch"
    if m in _SEDAN:
        return "sedan"
    blob = m + " " + t
    if any(k in blob for k in ("pickup", "pick-up", "pick up", "doble cabina", "hilux", "ranger",
                               "frontier", "tacoma", "d-max", "dmax", "l200", "np300", "f-150",
                               "f150", "amarok", "silverado", "tundra", "titan", "colorado",
                               "ridgeline", "raptor")):
        return "pickup"
    if any(k in blob for k in ("suv", "crossover", "4x4", "todo terreno", "jeepeta", "jeep",
                               "camioneta", "rav4", "tucson", "sportage", "santa fe", "explorer",
                               "cr-v", "grand cherokee", "land cruiser", "range rover", "prado")):
        return "suv"
    if any(k in blob for k in ("hatchback", " hatch", "5 puertas")):
        return "hatch"
    if any(k in blob for k in ("minivan", "microbus", "furgon", "furgón", "van ")):
        return "van"
    if any(k in blob for k in ("sedan", "sedán", "berlina", "4 puertas")):
        return "sedan"
    return "sedan"  # conservative default (most common class)


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def compute_quality_score(photo_count: int, price, year, km, make, model, location, fuel, transmission) -> int:
    photos = min(photo_count or 0, 6) / 6 * 40
    fields = [price, year, km, make, model, location, fuel, transmission]
    comp = sum(1 for f in fields if f not in (None, "", 0)) / len(fields) * 25
    km_n = _num(km)
    km_sc = 15 if (km_n is not None and 1000 < km_n < 400000) else (7 if km_n else 0)
    pr_n = _num(price)
    pr_sc = 8 if (pr_n is not None and 500 <= pr_n <= 200000) else 0
    yr_n = _num(year)
    yr_sc = max(0.0, min(1.0, ((yr_n - 2008) / 17))) * 12 if yr_n else 0
    return round(photos + comp + km_sc + pr_sc + yr_sc)


# ============================================================================
# CARLY (added) — deterministic NL intent parser over the live inventory.
# Swap the parser for an LLM later behind this same endpoint.
# ============================================================================
CARLY_COLS = (
    "id,country,url,make,model,year,km,price_usd,monthly_est,transmission,"
    "fuel_type,location,body_type,quality_score,photo_count,primary_photo"
)
MAKES = [
    "toyota", "nissan", "honda", "hyundai", "kia", "mitsubishi", "ford", "chevrolet", "mazda",
    "volkswagen", "suzuki", "jeep", "bmw", "mercedes", "audi", "lexus", "subaru", "land rover",
    "porsche", "cadillac",
]
TAGS = ["Mejor match", "Alternativa sólida", "Vale la pena"]


def _norm(s: str) -> str:
    s = (s or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        s = s.replace(a, b)
    return s


class Intent(BaseModel):
    body_types: List[str] = []
    price_max: Optional[int] = None
    price_min: Optional[int] = None
    transmission: Optional[str] = None
    make: Optional[str] = None
    use: Optional[str] = None
    newest_first: bool = False


def parse_intent(text: str) -> Intent:
    t = _norm(text)
    it = Intent()
    m_k = re.search(r"(\d+)\s*k\b", t)
    m_mil = re.search(r"(\d+)\s*mil", t)
    m_num = re.search(r"\$?\s*(\d{4,6})", t)
    val = None
    if m_k:
        val = int(m_k.group(1)) * 1000
    elif m_mil:
        val = int(m_mil.group(1)) * 1000
    elif m_num:
        val = int(m_num.group(1))
    if val:
        if re.search(r"(mas de|arriba|desde|minimo|min)", t):
            it.price_min = val
        else:
            it.price_max = val
    if re.search(r"(automatic|automatica|\bauto\b)", t):
        it.transmission = "Automática"
    elif re.search(r"(manual|mecanic|estandar)", t):
        it.transmission = "Manual"
    if re.search(r"(famili|nin|espacio|grande|hijos|esposa)", t):
        it.use = "familia"
        it.body_types = ["suv", "van"]
    if re.search(r"(primer auto|primer carro|economic|barat|ahorr|estudiante|economi)", t):
        it.use = "primer"
        it.body_types = ["sedan", "hatch"]
        if not it.price_max:
            it.price_max = 12000
    if re.search(r"(pickup|pick up|camioneta|trabajo|carga|negocio|finca)", t):
        it.use = "trabajo"
        it.body_types = ["pickup"]
    if re.search(r"(suv|crossover|todo terreno|4x4)", t):
        it.body_types = ["suv"]
    if re.search(r"\bsedan\b", t):
        it.body_types = ["sedan"]
    if re.search(r"(full|lujo|equipad|mas full|premium|\btop\b)", t):
        it.use = "full"
        it.newest_first = True
    for mk in MAKES:
        if mk in t:
            it.make = mk
            break
    return it


def build_why(car: dict, it: Intent) -> str:
    bits = []
    if it.use == "familia":
        bits.append("Espacio familiar")
    elif it.use == "trabajo":
        bits.append("Lista para trabajo")
    elif it.use == "primer":
        bits.append("Buen primer auto")
    elif it.use == "full":
        bits.append("De las más equipadas")
    else:
        bits.append("Sólida opción")
    if car.get("km"):
        bits.append(f"{int(car['km']):,} km reales")
    if it.price_max and car.get("price_usd") and car["price_usd"] <= it.price_max:
        bits.append("en tu presupuesto")
    return " · ".join(bits) + "."


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache.init_db()
    yield


app = FastAPI(title="CarTrade Link Resolver", version="1.5.0", lifespan=lifespan)

CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "https://cartrade.live,https://www.cartrade.live").split(",")
if os.environ.get("RESOLVER_DEV") == "1":
    CORS_ORIGINS = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class ResolveRequest(BaseModel):
    url: HttpUrl
    save: bool = False
    country: Optional[str] = None


class InventoryRunRequest(BaseModel):
    country: str = "sv"
    pages: int = 2


class CrautosInventoryRunRequest(BaseModel):
    limit: int = 50
    delay: float = 1.0


class CarlySearchRequest(BaseModel):
    q: str = ""
    country: Optional[str] = None
    limit: int = 3
    addressable_only: bool = True


@app.get("/")
async def root():
    return {
        "service": "cartrade-resolver",
        "version": "1.5.0",
        "endpoints": [
            "POST /resolve-link", "POST /inventory-run", "POST /inventory-run/crautos", "GET /inventory-preview",
            "POST /carly/search", "GET /stats", "GET /health",
        ],
        "supported_countries": list(COUNTRY_SEARCH_URLS.keys()),
    }


@app.get("/health")
async def health():
    return {
        "ok": True,
        "platforms": _health,
        "rate_limit": {
            "window_seconds": rate_limit.WINDOW_SECONDS,
            "max_requests": rate_limit.MAX_REQUESTS,
        },
        "cache_ttl_seconds": cache.CACHE_TTL_SECONDS,
        "supabase_connected": supabase is not None,
    }


@app.get("/inventory-preview")
async def inventory_preview(limit: int = 20, country: str | None = None):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not connected.")

    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 100.")

    query = supabase.table("scraped_listings").select("*").order("scraped_at", desc=True).limit(limit)

    if country:
        query = query.eq("country", country)

    response = query.execute()

    return {"count": len(response.data), "items": response.data}



@app.post("/inventory-run/crautos")
def inventory_run_crautos(body: CrautosInventoryRunRequest):
    if body.limit < 1 or body.limit > 500:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 500.")

    if body.delay < 0.5 or body.delay > 10:
        raise HTTPException(status_code=400, detail="Delay must be between 0.5 and 10 seconds.")

    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not connected.")

    try:
        from .scrapers.crautos import crautos_scraper as crautos
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"CRAutos scraper module not found: {e!s}",
        )

    import sys
    import sqlite3
    import time as time_module

    started = time_module.time()
    db_path = "/tmp/crautos.db"

    old_argv = sys.argv[:]
    try:
        sys.argv = [
            "crautos_scraper.py",
            "--db", db_path,
            "--limit", str(body.limit),
            "--delay", str(body.delay),
        ]
        crautos.main()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CRAutos scraper failed: {e!s}")
    finally:
        sys.argv = old_argv

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT * FROM cars ORDER BY scraped_at DESC LIMIT ?",
        (body.limit,)
    ).fetchall()

    saved_count = 0
    error_count = 0
    no_photo_count = 0

    for row in rows:
        try:
            r = dict(row)

            photos = []
            if r.get("fotos"):
                photos = [p for p in r["fotos"].split("|") if p]

            if not photos:
                no_photo_count += 1

            title = " ".join(
                str(x) for x in [r.get("marca"), r.get("modelo"), r.get("anio")]
                if x
            )

            make_value = r.get("marca")
            model_value = r.get("modelo")
            price_value = r.get("precio_usd")
            year_value = r.get("anio")
            km_value = r.get("kilometraje")
            location_value = r.get("provincia")
            fuel_value = normalize_fuel(r.get("combustible"))
            transmission_value = normalize_transmission(r.get("transmision"))
            primary_photo = photos[0] if photos else None

            body_type_value = classify_body_type(model_value, title)
            quality_value = compute_quality_score(
                len(photos),
                price_value,
                year_value,
                km_value,
                make_value,
                model_value,
                location_value,
                fuel_value,
                transmission_value,
            )

            db_record = {
                "source": "crautos",
                "country": "cr",
                "url": r.get("url"),
                "make": make_value,
                "model": model_value,
                "fuel_type": fuel_value,
                "transmission": transmission_value,
                "title": title,
                "price_usd": price_value,
                "year": year_value,
                "km": km_value,
                "location": location_value,
                "photos": photos,
                "photo_count": len(photos),
                "primary_photo": primary_photo,
                "body_type": body_type_value,
                "quality_score": quality_value,
                "raw_payload": r,
                "status": "staging",
            }

            supabase.table("scraped_listings").upsert(
                db_record,
                on_conflict="url"
            ).execute()

            saved_count += 1

        except Exception:
            error_count += 1
            log.exception("CRAutos Supabase upsert error")

    discovered_count = 0
    try:
        with open("/tmp/crautos_ids.txt", "r") as f:
            discovered_count = len([x for x in f.read().splitlines() if x.strip()])
    except Exception:
        discovered_count = len(rows)

    return {
        "source": "crautos",
        "country": "cr",
        "limit": body.limit,
        "delay": body.delay,
        "discovered_count": discovered_count,
        "saved_count": saved_count,
        "error_count": error_count,
        "no_photo_count": no_photo_count,
        "supabase_connected": supabase is not None,
        "elapsed_seconds": round(time_module.time() - started, 2),
        "sample_urls": [dict(r).get("url") for r in rows[:5]],
    }



@app.post("/inventory-run")
async def inventory_run(body: InventoryRunRequest):
    return await _ingest_country(body.country, body.pages)


# ── Run-all trigger ──────────────────────────────────────────────────────
# One GET kicks off every Central-American country in the background, so a
# free cloud cron (e.g. cron-job.org) can keep the index fresh with nobody
# running anything locally. The HTTP call returns immediately; the work
# continues in the background. Check /inventory-status for progress.
CA_COUNTRIES = ["sv", "pa", "gt", "cr", "hn", "ni"]

INVENTORY_JOB_STATUS = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "current_country": None,
    "pages": None,
    "results": {},
    "last_error": None,
}


async def _run_all_ca(pages: int):
    INVENTORY_JOB_STATUS.update(
        running=True, started_at=_now_iso(), finished_at=None,
        current_country=None, pages=pages, results={}, last_error=None,
    )
    try:
        for country in CA_COUNTRIES:
            INVENTORY_JOB_STATUS["current_country"] = country
            try:
                summary = await _ingest_country(country, pages)
                INVENTORY_JOB_STATUS["results"][country] = {
                    "discovered": summary.get("discovered_count"),
                    "saved": summary.get("saved_count"),
                    "errors": summary.get("error_count"),
                }
            except Exception as e:
                INVENTORY_JOB_STATUS["results"][country] = {"error": str(e)}
                INVENTORY_JOB_STATUS["last_error"] = f"{country}: {e!s}"
                log.exception("run-all failed for %s", country)
            await asyncio.sleep(random.uniform(5, 12))
    finally:
        INVENTORY_JOB_STATUS["current_country"] = None
        INVENTORY_JOB_STATUS["finished_at"] = _now_iso()
        INVENTORY_JOB_STATUS["running"] = False


@app.get("/inventory-run-all")
async def inventory_run_all(pages: int = 40, token: str | None = None):
    """Trigger a full Central-America ingestion in the background.
    Open this URL (or point a cron at it) to refresh the whole index.
    If the CRON_TOKEN env var is set, ?token= must match it."""
    expected = os.environ.get("CRON_TOKEN")
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="invalid token")
    if pages < 1 or pages > 200:
        raise HTTPException(status_code=400, detail="pages must be 1-200")
    if INVENTORY_JOB_STATUS["running"]:
        return {"status": "already_running", "progress": INVENTORY_JOB_STATUS}

    asyncio.create_task(_run_all_ca(pages))
    return {
        "status": "started",
        "countries": CA_COUNTRIES,
        "pages": pages,
        "check_progress_at": "/inventory-status",
    }


@app.get("/inventory-status")
async def inventory_status():
    return INVENTORY_JOB_STATUS


# ── Rotating runner: ONE country per call ────────────────────────────────
# Each cron hit scrapes a single country (the one least-recently updated, or
# any country with no data yet) and rotates. Short calls that actually finish,
# instead of one long call Render kills halfway. Over a few hits, all 6 fill.
async def _pick_next_country() -> str:
    """The stalest CA country: never-scraped first, else oldest updated_at."""
    if not supabase:
        return CA_COUNTRIES[0]
    oldest_country = CA_COUNTRIES[0]
    oldest_ts = None
    for c in CA_COUNTRIES:
        try:
            rows = (supabase.table("scraped_listings")
                    .select("updated_at")
                    .eq("source", "encuentra24").eq("country", c)
                    .order("updated_at", desc=True).limit(1).execute().data)
        except Exception:
            rows = []
        if not rows:
            return c  # never scraped -> highest priority
        ts = rows[0].get("updated_at") or ""
        if oldest_ts is None or ts < oldest_ts:
            oldest_ts = ts
            oldest_country = c
    return oldest_country


async def _run_one(country: str, pages: int):
    INVENTORY_JOB_STATUS.update(
        running=True, started_at=_now_iso(), finished_at=None,
        current_country=country, pages=pages, results={}, last_error=None,
    )
    try:
        summary = await _ingest_country(country, pages)
        INVENTORY_JOB_STATUS["results"][country] = {
            "discovered": summary.get("discovered_count"),
            "saved": summary.get("saved_count"),
            "errors": summary.get("error_count"),
        }
    except Exception as e:
        INVENTORY_JOB_STATUS["last_error"] = f"{country}: {e!s}"
        log.exception("run-one failed for %s", country)
    finally:
        INVENTORY_JOB_STATUS["current_country"] = None
        INVENTORY_JOB_STATUS["finished_at"] = _now_iso()
        INVENTORY_JOB_STATUS["running"] = False


@app.get("/inventory-run-next")
async def inventory_run_next(pages: int = 30, token: str | None = None,
                             country: str | None = None):
    """Scrape ONE country in the background. By default picks the stalest and
    rotates; pass ?country=ni to force a specific one (useful for first fill of
    big countries with high pages, e.g. ?country=ni&pages=90)."""
    expected = os.environ.get("CRON_TOKEN")
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="invalid token")
    if pages < 1 or pages > 200:
        raise HTTPException(status_code=400, detail="pages must be 1-200")
    if INVENTORY_JOB_STATUS["running"]:
        return {"status": "already_running", "progress": INVENTORY_JOB_STATUS}

    if country:
        country = country.lower().strip()
        if country not in COUNTRY_SEARCH_URLS:
            raise HTTPException(status_code=400,
                detail=f"Unsupported country. Use one of: {', '.join(COUNTRY_SEARCH_URLS.keys())}")
        picked, mode = country, "forced"
    else:
        picked, mode = await _pick_next_country(), "auto (stalest)"

    asyncio.create_task(_run_one(picked, pages))
    return {
        "status": "started",
        "country": picked,
        "selection": mode,
        "pages": pages,
        "check_progress_at": "/inventory-status",
    }


@app.get("/inventory-sweep-inactive")
async def inventory_sweep_inactive(days: int = 7, token: str | None = None):
    """Mark as 'inactivo' the encuentra24 listings not seen in `days` days, and
    reactivate any that reappeared. Scoped to encuentra24 (the regularly
    re-scraped source) so crautos cars aren't wrongly retired. Never touches
    'reservado'/'vendido' (manual states). Run by cron (e.g. daily) or by hand.

    NOTE: needs last_seen_at populated, so it only acts after a listing has been
    seen once and then missed for `days` — a deliberate warm-up, not a bug."""
    expected = os.environ.get("CRON_TOKEN")
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="invalid token")
    if not supabase:
        return {"error": "supabase not connected"}
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    retired = reactivated = 0
    try:
        r = (supabase.table("scraped_listings")
             .update({"listing_state": "inactivo"})
             .eq("source", "encuentra24")
             .lt("last_seen_at", cutoff)
             .or_("listing_state.is.null,listing_state.eq.activo")
             .execute())
        retired = len(r.data or [])
    except Exception as e:
        log.exception("sweep retire error")
        return {"error": str(e)[:200]}
    try:
        r = (supabase.table("scraped_listings")
             .update({"listing_state": "activo"})
             .eq("source", "encuentra24")
             .gte("last_seen_at", cutoff)
             .eq("listing_state", "inactivo")
             .execute())
        reactivated = len(r.data or [])
    except Exception:
        log.exception("sweep reactivate error")
    return {"days": days, "cutoff": cutoff, "retired": retired, "reactivated": reactivated}


@app.post("/listing-state")
async def listing_state(url: str, state: str, token: str | None = None):
    """Manually set a car's state: activo / reservado / vendido.
    The two CarTrade moments (reserved, sold) live here."""
    expected = os.environ.get("CRON_TOKEN")
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="invalid token")
    state = (state or "").lower().strip()
    if state not in {"activo", "reservado", "vendido"}:
        raise HTTPException(status_code=400, detail="state must be activo|reservado|vendido")
    if not supabase:
        return {"error": "supabase not connected"}
    try:
        r = (supabase.table("scraped_listings")
             .update({"listing_state": state})
             .eq("url", url).execute())
        return {"url": url, "state": state, "updated": len(r.data or [])}
    except Exception as e:
        log.exception("listing-state error")
        return {"error": str(e)[:200]}


async def _ingest_country(country: str, pages: int) -> dict:
    country = (country or "").lower().strip()

    if country not in COUNTRY_SEARCH_URLS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported country. Use one of: {', '.join(COUNTRY_SEARCH_URLS.keys())}"
        )

    if pages < 1 or pages > 200:
        raise HTTPException(status_code=400, detail="Pages must be between 1 and 200.")

    search_url = COUNTRY_SEARCH_URLS[country]
    discovered_urls = set()
    page_debug = []

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "es;q=0.9"},
    ) as cli:
        for page in range(1, pages + 1):
            page_url = f"{search_url}?page={page}"
            r = await cli.get(page_url)
            r.raise_for_status()

            tree = HTMLParser(r.text)
            page_urls = set()

            for node in tree.css("a[href]"):
                href = node.attributes.get("href", "")

                if "/autos-usados/" not in href:
                    continue

                if href.startswith("/"):
                    href = "https://www.encuentra24.com" + href

                href = href.split("?")[0]

                if re.search(r"/\d+$", href):
                    page_urls.add(href)

            discovered_urls.update(page_urls)
            page_debug.append({
                "page": page,
                "page_url": page_url,
                "found_count": len(page_urls),
                "sample_urls": sorted(page_urls)[:5],
            })

    saved_count = 0
    error_count = 0
    no_photo_count = 0

    for i, url in enumerate(sorted(discovered_urls), start=1):
        try:
            listing = await encuentra24.resolve(url)
            payload = listing.to_dict()

            title_value = field_value(payload, "title")
            description_value = field_value(payload, "description")
            text_for_inference = f"{title_value or ''} {description_value or ''}"

            fuel_value = normalize_fuel(field_value(payload, "fuel")) or infer_fuel_from_text(text_for_inference)
            transmission_value = normalize_transmission(field_value(payload, "transmission")) or infer_transmission_from_text(text_for_inference)

            cleaned_photos = clean_photos(payload.get("photos", []), url)
            if not cleaned_photos:
                no_photo_count += 1

            photo = cleaned_photos[0] if cleaned_photos else None
            thumb = to_medium_photo(photo) if photo else None

            payload["inventory_source"] = "encuentra24"
            payload["inventory_country"] = country
            payload["inventory_scraped_at"] = int(time.time())
            payload["cleaned_photos"] = cleaned_photos
            payload["photo"] = photo
            payload["thumb"] = thumb

            if supabase:
                make_value = field_value(payload, "make")
                model_value = field_value(payload, "model")
                price_value = field_value(payload, "price_usd")
                year_value = field_value(payload, "year")
                km_value = field_value(payload, "km")
                location_value = field_value(payload, "location")

                # --- enrichment (added): populate body_type/quality_score/photo_count/primary_photo
                body_type_value = classify_body_type(model_value, title_value)
                quality_value = compute_quality_score(
                    len(cleaned_photos), price_value, year_value, km_value,
                    make_value, model_value, location_value, fuel_value, transmission_value,
                )

                db_record = {
                    "source": "encuentra24",
                    "country": country,
                    "url": url,
                    "make": make_value,
                    "model": model_value,
                    "fuel_type": fuel_value,
                    "transmission": transmission_value,
                    "title": title_value,
                    "price_usd": price_value,
                    "currency": field_value(payload, "currency"),
                    "year": year_value,
                    "km": km_value,
                    "location": location_value,
                    "photos": cleaned_photos,
                    "photo_count": len(cleaned_photos),       # added
                    "primary_photo": photo,                    # added
                    "body_type": body_type_value,              # added
                    "quality_score": quality_value,            # added
                    "raw_payload": payload,
                    "updated_at": _now_iso(),                  # added: refresh on every re-scrape
                    "last_seen_at": _now_iso(),                # added: drives inactive sweep
                    "status": "staging",
                }

                supabase.table("scraped_listings").upsert(db_record, on_conflict="url").execute()
                saved_count += 1

        except Exception as e:
            error_count += 1
            log.exception("inventory resolver error url=%s", url)

        time.sleep(0.5)

    return {
        "country": country,
        "pages": pages,
        "discovered_count": len(discovered_urls),
        "resolved_count": len(discovered_urls),
        "saved_count": saved_count,
        "error_count": error_count,
        "no_photo_count": no_photo_count,
        "page_debug": page_debug,
    }


def _client_ip(req: Request) -> str:
    xff = req.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return req.client.host if req.client else "unknown"


_E24_COUNTRY_SLUG = {
    "el-salvador": "sv", "panama": "pa", "guatemala": "gt",
    "costa-rica": "cr", "honduras": "hn", "nicaragua": "ni",
}


def _infer_country(url: str) -> Optional[str]:
    """Best-effort country from the URL (works for Encuentra24 links)."""
    low = url.lower()
    for slug, code in _E24_COUNTRY_SLUG.items():
        if f"/{slug}-" in low or f"/{slug}/" in low:
            return code
    return None


# Bad-link filter (REJECT, not quarantine). A pasted/resolved link only enters
# inventory if it passes ALL gates: usable essentials + looks like a real car +
# has usable data. Filters out junk seen in logs ("vendo bocina", motorcycles).
_VALID_BODY = {"suv", "sedan", "pickup", "hatch", "hatchback", "van",
               "coupe", "wagon", "convertible", "minivan", "crossover"}
_BAD_MAKE = {"", "otros", "otro", "other", "varios", "n/a", "na", "none", "desconocido"}


def _is_valid_car_listing(payload: dict, url: str = "", platform: str = "") -> tuple[bool, str]:
    """True if this resolved listing should enter inventory. Returns (ok, reason)."""
    # Category gate (Encuentra24): the link must be in the used-cars section.
    # Catches real-estate / electronics / etc. pasted by mistake (e.g. a house in
    # /bienes-raices-.../) before we even look at content.
    if platform == "encuentra24" and "autos-usados" not in (url or "").lower():
        return False, "el link no es de la sección de autos (categoría incorrecta)"
    title = field_value(payload, "title")
    photos = payload.get("photos", []) or []
    if not title and not photos:
        return False, "sin título ni foto"
    make = (field_value(payload, "make") or "").strip()
    model = field_value(payload, "model")
    body = (classify_body_type(model, title) or "").lower()
    price = field_value(payload, "price_usd")
    year = field_value(payload, "year")
    make_ok = make.lower() not in _BAD_MAKE
    body_ok = body in _VALID_BODY
    if not (make_ok or body_ok):
        return False, "no parece un carro (marca/carrocería no reconocida)"
    if not (price or (make_ok and year)):
        return False, "sin datos usables (falta precio o marca+año)"
    return True, "ok"


def _build_db_record(payload: dict, source: str, country: Optional[str], url: str) -> dict:
    """Turn a resolved listing payload into a scraped_listings row.
    Same shape and enrichment used by the inventory crawler, so links
    submitted by hand/WhatsApp/web land in inventory identically."""
    title_value = field_value(payload, "title")
    description_value = field_value(payload, "description")
    text_for_inference = f"{title_value or ''} {description_value or ''}"

    fuel_value = normalize_fuel(field_value(payload, "fuel")) or infer_fuel_from_text(text_for_inference)
    transmission_value = normalize_transmission(field_value(payload, "transmission")) or infer_transmission_from_text(text_for_inference)

    cleaned_photos = clean_photos(payload.get("photos", []), url)
    photo = cleaned_photos[0] if cleaned_photos else None

    make_value = field_value(payload, "make")
    model_value = field_value(payload, "model")
    price_value = field_value(payload, "price_usd")
    year_value = field_value(payload, "year")
    km_value = field_value(payload, "km")
    location_value = field_value(payload, "location")

    body_type_value = classify_body_type(model_value, title_value)
    quality_value = compute_quality_score(
        len(cleaned_photos), price_value, year_value, km_value,
        make_value, model_value, location_value, fuel_value, transmission_value,
    )

    return {
        "source": source,
        "country": country,
        "url": url,
        "make": make_value,
        "model": model_value,
        "fuel_type": fuel_value,
        "transmission": transmission_value,
        "title": title_value,
        "price_usd": price_value,
        "currency": field_value(payload, "currency"),
        "year": year_value,
        "km": km_value,
        "location": location_value,
        "photos": cleaned_photos,
        "photo_count": len(cleaned_photos),
        "primary_photo": photo,
        "body_type": body_type_value,
        "quality_score": quality_value,
        "raw_payload": payload,
        "updated_at": _now_iso(),
        "last_seen_at": _now_iso(),
        "status": "staging",
    }


_PUBLICAR_HTML = """<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Publica tu carro</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 540px;
         margin: 0 auto; padding: 24px; line-height: 1.5; }
  h1 { font-size: 22px; font-weight: 600; }
  p.sub { color: #666; margin-top: -8px; }
  input { width: 100%; padding: 14px; font-size: 16px; border: 1px solid #ccc;
          border-radius: 10px; box-sizing: border-box; margin: 12px 0; }
  button { width: 100%; padding: 14px; font-size: 16px; font-weight: 600;
           border: 0; border-radius: 10px; background: #111; color: #fff; cursor: pointer; }
  button:disabled { opacity: .5; }
  #out { margin-top: 20px; }
  .card { border: 1px solid #ddd; border-radius: 12px; overflow: hidden; }
  .card img { width: 100%; display: block; }
  .card .body { padding: 14px; }
  .ok { color: #0a7d2c; font-weight: 600; }
  .err { color: #b00; }
</style></head><body>
<h1>Publica tu carro</h1>
<p class="sub">Pega el link de tu carro (Facebook, Encuentra24, etc.) y lo publicamos.</p>
<input id="url" type="url" placeholder="https://..." autocomplete="off">
<button id="go" onclick="publicar()">Publicar</button>
<div id="out"></div>
<script>
async function publicar() {
  const url = document.getElementById('url').value.trim();
  const out = document.getElementById('out');
  const btn = document.getElementById('go');
  if (!url) { out.innerHTML = '<p class="err">Pega un link primero.</p>'; return; }
  btn.disabled = true; out.innerHTML = 'Procesando...';
  try {
    const r = await fetch('/resolve-link', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ url: url, save: true })
    });
    const d = await r.json();
    if (d.saved) {
      const t = (d.title && d.title.value) || 'Tu carro';
      const p = (d.price_usd && d.price_usd.value) ? ('$' + d.price_usd.value.toLocaleString()) : '';
      const img = (d.photos && d.photos[0]) || '';
      out.innerHTML = '<p class="ok">\u2705 Publicado</p><div class="card">' +
        (img ? '<img src="' + img + '">' : '') +
        '<div class="body"><strong>' + t + '</strong><br>' + p + '</div></div>';
    } else {
      out.innerHTML = '<p class="err">No se pudo guardar: ' + (d.save_error || d.detail || 'intenta otro link') + '</p>';
    }
  } catch (e) {
    out.innerHTML = '<p class="err">Error de conexi\u00f3n. Intenta de nuevo.</p>';
  } finally { btn.disabled = false; }
}
</script></body></html>"""


@app.get("/publicar", response_class=HTMLResponse)
async def publicar_page():
    return _PUBLICAR_HTML


@app.post("/resolve-link")
async def resolve_link(body: ResolveRequest, request: Request):
    url = str(body.url)
    ip = _client_ip(request)

    allowed, remaining = rate_limit.check(ip)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    if not platforms.is_allowed(url):
        raise HTTPException(status_code=400, detail="URL is not from a supported listing platform.")

    cached = cache.get(url)
    if cached and not body.save:
        cached["cached"] = True
        return cached

    platform = platforms.detect(url)
    started = time.time()

    try:
        if platform == "encuentra24":
            listing = await encuentra24.resolve(url)
        elif platform == "olx":
            listing = await olx.resolve(url)
        elif platform == "facebook":
            listing = await facebook.resolve(url)
        elif platform == "mercadolibre":
            listing = await mercadolibre.resolve(url)
        else:
            listing = await fallback.resolve(url)
    except Exception as e:
        _record(platform, ok=False, error=str(e)[:200])
        raise HTTPException(status_code=500, detail=f"Resolver error: {e!s}")

    elapsed = time.time() - started
    has_essentials = listing.title is not None or len(listing.photos) > 0
    _record(platform, ok=has_essentials and not listing.errors,
            error="; ".join(listing.errors)[:200] if listing.errors else None)

    payload = listing.to_dict()
    payload["elapsed_seconds"] = round(elapsed, 2)

    # --- added: tell the frontend whether this listing is already in our inventory
    if supabase:
        try:
            existing = supabase.table("scraped_listings").select("id").eq("url", url).limit(1).execute().data
            payload["in_inventory"] = bool(existing)
        except Exception:
            payload["in_inventory"] = None

    # --- SAVE into inventory: by default for any NEW valid car (AUTO_SAVE_LINKS),
    # or when explicitly requested (body.save). Bad links are REJECTED, not saved.
    want_save = bool(body.save) or AUTO_SAVE_LINKS
    if want_save:
        valid, reason = _is_valid_car_listing(payload, url=url, platform=platform)
        if not supabase:
            payload["saved"] = False
            payload["save_error"] = "supabase not connected"
        elif not valid:
            payload["saved"] = False
            payload["rejected_reason"] = reason  # did not meet inventory bar
        else:
            try:
                country = (body.country or _infer_country(url) or "").lower().strip() or None
                record = _build_db_record(payload, source=platform, country=country, url=url)
                supabase.table("scraped_listings").upsert(record, on_conflict="url").execute()
                payload["saved"] = True
                payload["saved_country"] = country
            except Exception as e:
                payload["saved"] = False
                payload["save_error"] = str(e)[:200]
                log.exception("resolve-link save error url=%s", url)

    if has_essentials:
        cache.put(url, payload)

    return payload


# ── WhatsApp door (Carly on WhatsApp) ────────────────────────────────────
# One number, two jobs: if a seller sends a car (link), Carly saves it; if a
# buyer asks for a car (text), Carly searches inventory. Needs three env vars
# in Render: WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN.
_URL_RE = re.compile(r"https?://\S+")


async def _wa_send(to: str, body: str) -> None:
    token = os.environ.get("WHATSAPP_TOKEN")
    pnid = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    ver = os.environ.get("WHATSAPP_API_VERSION", "v22.0")
    if not token or not pnid:
        log.warning("WA send skipped: missing WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID")
        return
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(
                f"https://graph.facebook.com/{ver}/{pnid}/messages",
                headers={"Authorization": f"Bearer {token}"},
                json={"messaging_product": "whatsapp", "to": to,
                      "type": "text", "text": {"body": body[:4000]}},
            )
            if r.status_code >= 400:
                log.warning("WA send error %s: %s", r.status_code, r.text[:300])
    except Exception:
        log.exception("WA send failed")


async def _ingest_link(url: str, country: Optional[str] = None) -> dict:
    """Resolve a pasted link and save it to inventory. Returns a small summary."""
    if not platforms.is_allowed(url):
        return {"ok": False, "saved": False}
    platform = platforms.detect(url)
    try:
        if platform == "encuentra24":
            listing = await encuentra24.resolve(url)
        elif platform == "olx":
            listing = await olx.resolve(url)
        elif platform == "facebook":
            listing = await facebook.resolve(url)
        elif platform == "mercadolibre":
            listing = await mercadolibre.resolve(url)
        else:
            listing = await fallback.resolve(url)
    except Exception:
        log.exception("WA ingest resolver error url=%s", url)
        return {"ok": False, "saved": False}

    payload = listing.to_dict()
    has_essentials = listing.title is not None or len(listing.photos) > 0
    saved = False
    if has_essentials and supabase:
        try:
            c = (country or _infer_country(url) or "").lower().strip() or None
            record = _build_db_record(payload, source=platform, country=c, url=url)
            supabase.table("scraped_listings").upsert(record, on_conflict="url").execute()
            saved = True
        except Exception:
            log.exception("WA ingest save error url=%s", url)
    return {"ok": has_essentials, "saved": saved, "payload": payload}


async def _handle_wa_text(sender: str, text: str) -> None:
    text = (text or "").strip()
    if not text:
        return
    m = _URL_RE.search(text)

    # Seller sent a car (link) -> save it
    if m:
        url = m.group(0).rstrip(").,;")
        res = await _ingest_link(url)
        if res.get("saved"):
            p = res["payload"]
            title = field_value(p, "title") or "tu carro"
            price = field_value(p, "price_usd")
            price_s = f" — ${price:,}" if price else ""
            await _wa_send(sender, f"\u2705 Listo, guard\u00e9 {title}{price_s}. \u00a1Gracias!")
        else:
            await _wa_send(sender, "No pude leer ese link (Facebook a veces lo bloquea). "
                                   "M\u00e1ndame una foto del carro con marca, a\u00f1o y precio y lo public\u00e9.")
        return

    # Buyer asked for a car (text) -> search inventory
    try:
        result = await carly_search(CarlySearchRequest(q=text, limit=3))
        items = result.get("results", [])
    except Exception:
        items = []
    if not items:
        await _wa_send(sender, "No encontr\u00e9 nada con eso. Prueba algo como: "
                               "\"SUV autom\u00e1tico bajo $15mil\".")
        return
    parts = ["Esto encontr\u00e9:"]
    for c in items:
        name = " ".join(str(x) for x in (c.get("make"), c.get("model"), c.get("year")) if x)
        price = c.get("price_usd")
        price_s = f"${price:,}" if price else "precio a confirmar"
        loc = c.get("location")
        tail = f" \u00b7 {loc}" if loc else ""
        parts.append(f"\u2022 {name} — {price_s}{tail}\n{c.get('url')}")
    await _wa_send(sender, "\n\n".join(parts))


@app.get("/whatsapp/webhook")
async def wa_verify(request: Request):
    """Meta calls this once to verify the webhook (handshake)."""
    p = request.query_params
    expected = os.environ.get("WHATSAPP_VERIFY_TOKEN")
    if p.get("hub.mode") == "subscribe" and expected and p.get("hub.verify_token") == expected:
        return PlainTextResponse(p.get("hub.challenge") or "")
    raise HTTPException(status_code=403, detail="verification failed")


@app.post("/whatsapp/webhook")
async def wa_incoming(request: Request):
    """Incoming WhatsApp messages. Returns 200 immediately and works in background."""
    try:
        data = await request.json()
    except Exception:
        return {"status": "ignored"}
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    sender = msg.get("from")
                    if not sender:
                        continue
                    if msg.get("type") == "text":
                        asyncio.create_task(_handle_wa_text(sender, (msg.get("text") or {}).get("body", "")))
                    elif msg.get("type") == "image":
                        cap = (msg.get("image") or {}).get("caption", "")
                        if cap.strip():
                            asyncio.create_task(_handle_wa_text(sender, cap))
                        else:
                            asyncio.create_task(_wa_send(
                                sender,
                                "Recib\u00ed tu foto \U0001F4F8. Escr\u00edbeme marca, a\u00f1o y precio "
                                "(ej: \"Toyota Hilux 2015 $18,000\") y lo public\u00e9."))
                    else:
                        asyncio.create_task(_wa_send(
                            sender, "M\u00e1ndame el link del carro, o una foto con marca, a\u00f1o y precio."))
    except Exception:
        log.exception("WA incoming parse error")
    return {"status": "ok"}


def _norm_model(model) -> str:
    """Misma normalización que scraped_listings.model_norm: mayúsculas, sin guiones/espacios."""
    import re
    return re.sub(r"[-\s]", "", str(model or "").upper()).strip()


_TIER_BRANDS = {
    "japones": {"toyota","honda","nissan","mazda","mitsubishi","subaru","suzuki","daihatsu","isuzu","lexus","scion"},
    "coreano": {"kia","hyundai","genesis","ssangyong"},
    "lujo": {"mercedes-benz","mercedes","bmw","audi","land rover","porsche","jaguar","infiniti","acura","volvo","cadillac","mini"},
    "electrico": {"tesla","byd","mg"},
}
def _brand_tier(make) -> str:
    m = (make or "").lower().strip()
    for t, brands in _TIER_BRANDS.items():
        if m in brands:
            return t
    return "popular"


# Cache de fichas/plantillas (tablas chicas: 30 + 18). Se cargan una vez por proceso.
_CHARACTER_CACHE = {"cards": None, "templates": None}
def _load_character_tables():
    if _CHARACTER_CACHE["cards"] is not None:
        return
    cards, tpls = {}, {}
    try:
        for r in (supabase.table("model_cards").select("make,model_norm,card").execute().data or []):
            cards[(r["make"].lower(), r["model_norm"])] = r["card"]
        for r in (supabase.table("segment_templates").select("body_type,tier,template").execute().data or []):
            tpls[(r["body_type"], r["tier"])] = r["template"]
    except Exception:
        log.exception("no se pudieron cargar fichas/plantillas")
    _CHARACTER_CACHE["cards"], _CHARACTER_CACHE["templates"] = cards, tpls


def _character_for(car: dict) -> dict | None:
    """Carácter de un carro: ficha individual primero; si no, plantilla de casillero; si no, None."""
    _load_character_tables()
    cards, tpls = _CHARACTER_CACHE["cards"] or {}, _CHARACTER_CACHE["templates"] or {}
    key = ((car.get("make") or "").lower(), _norm_model(car.get("model")))
    if key in cards:
        return {"source": "card", "data": cards[key]}
    tkey = (car.get("body_type"), _brand_tier(car.get("make")))
    if tkey in tpls:
        return {"source": "template", "data": tpls[tkey]}
    return None


def _decision_rank(rows: list, top_n: int) -> list:
    """Re-rank candidates at query time by a layered score (works on existing
    inventory, no re-scoring needed). Layers (0-1, weighted):
      deal-vs-comparable-group (auto-off where sparse) + km gradient +
      age-adjusted km + year. Outlier guard: prices >55% below the comparable
      median are flagged suspicious (likely bad data), not surfaced as deals.
      Hidden states (vendido/inactivo) are dropped. NOTE: text-signal layer
      (dueño único / agencia) is deferred — needs description in the query."""
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        p = r.get("price_usd")
        if p:
            groups[(r.get("country"), (r.get("make") or "").lower(),
                    (r.get("model") or "").lower())].append(p)
    med = {k: sorted(v)[len(v) // 2] for k, v in groups.items() if len(v) >= 5}

    scored = []
    for r in rows:
        st = (r.get("listing_state") or "activo").lower()
        if st in ("vendido", "inactivo"):
            continue
        km = r.get("km"); year = r.get("year"); price = r.get("price_usd")
        age = max(2026 - year, 0) if year else None
        km_g = 1 - min((km or 0) / 250000, 1) if km is not None else 0.5
        if km is not None and age:
            kpy = km / max(age, 1); aadj = 1 - min(abs(kpy - 15000) / 40000, 1)
        else:
            aadj = 0.5
        yr = min(max(((year or 2008) - 2008) / 17, 0), 1)
        key = (r.get("country"), (r.get("make") or "").lower(), (r.get("model") or "").lower())
        deal = 0.5; dconf = 0.0; vs = None; suspicious = False
        if price and key in med and med[key] > 0:
            disc = (med[key] - price) / med[key]; vs = round(disc * 100)
            if disc > 0.55:                      # outlier guard: too good = bad data
                suspicious = True; deal = 0.0; dconf = 1.0
            else:
                deal = min(max((disc + 0.3) / 0.6, 0), 1); dconf = 1.0
        w_deal = 0.40 * dconf
        w = w_deal + 0.25 + 0.20 + 0.15
        score = (w_deal * deal + 0.25 * km_g + 0.20 * aadj + 0.15 * yr) / w
        scored.append({"score": round(score * 100), "vs_market": vs,
                       "suspicious": suspicious, "state": st, "car": r})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


@app.post("/carly/search")
async def carly_search(body: CarlySearchRequest):
    """Carly: parse a Spanish query, match the live inventory, re-rank by the
    layered decision score, and return top N."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not connected.")

    it = parse_intent(body.q)
    q = supabase.table("scraped_listings").select(CARLY_COLS + ",listing_state")

    if body.addressable_only:
        q = q.eq("is_addressable", True)
    if body.country:
        q = q.eq("country", body.country)
    if it.body_types:
        q = q.in_("body_type", it.body_types)
    if it.transmission:
        q = q.eq("transmission", it.transmission)
    if it.make:
        q = q.ilike("make", f"%{it.make}%")
    if it.price_max:
        q = q.lte("price_usd", it.price_max)
    if it.price_min:
        q = q.gte("price_usd", it.price_min)

    # Fetch a larger CANDIDATE POOL (prefiltered by completeness), then re-rank.
    if it.use == "primer":
        q = q.order("price_usd", desc=False)
    elif it.newest_first:
        q = q.order("year", desc=True)
    else:
        q = q.order("quality_score", desc=True)

    limit = max(1, min(body.limit, 12))
    try:
        pool = q.limit(300).execute().data or []
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Supabase query failed: {e!s}")

    total_matching = len(pool)            # for the transparency line ("de N, estos M")
    ranked = _decision_rank(pool, limit)

    results = []
    for i, item in enumerate(ranked):
        car = item["car"]
        char = _character_for(car)                      # ficha o plantilla (o None)
        bits = []
        if item["vs_market"] and item["vs_market"] >= 12 and not item["suspicious"]:
            bits.append(f"{item['vs_market']}% bajo similares")
        # "gana en" desde la ficha/plantilla, si hay
        if char and char["source"] == "card":
            gana = char["data"].get("gana_vs_pares_en") or []
            if gana:
                bits.append("destaca en " + " y ".join(gana[:2]))
        bits.append(build_why(car, it))
        why = " · ".join(b for b in bits if b)

        character_out = None
        if char:
            cd = char["data"]
            character_out = {
                "source": char["source"],                # "card" = ficha fina, "template" = heredada
                "one_line": cd.get("one_line"),
                "gana_vs_pares_en": cd.get("gana_vs_pares_en"),
                "persona_fit": cd.get("persona_fit"),
                "better_if_user_prioritizes": cd.get("better_if_user_prioritizes"),
                "user_facing": cd.get("user_facing"),
                "review_status": cd.get("review_status", "unverified_ai_generated"),
            }

        results.append({
            **{k: car.get(k) for k in (
                "id", "country", "url", "make", "model", "year", "km", "price_usd",
                "monthly_est", "transmission", "location", "body_type",
                "quality_score", "primary_photo",
            )},
            "tag": TAGS[i] if i < len(TAGS) else "Opción",
            "match_score": item["score"],
            "vs_market_pct": item["vs_market"],
            "price_flag": "verificar precio" if item["suspicious"] else None,
            "reserved": item["state"] == "reservado",
            "why": why,
            "character": character_out,                  # NUEVO: carácter del modelo
        })

    return {"query": body.q, "intent": it.model_dump(),
            "pool_matching": total_matching, "count": len(results),
            "results": results}


@app.get("/stats")
async def stats():
    """Inventory-domination metrics by country (for the landing / pitch)."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not connected.")

    try:
        rows = supabase.table("scraped_listings").select("country,price_usd,is_addressable").execute().data or []
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Supabase query failed: {e!s}")

    agg = {}
    for r in rows:
        c = r.get("country") or "??"
        a = agg.setdefault(c, {"indexed": 0, "addressable": 0, "gmv_usd": 0})
        a["indexed"] += 1
        if r.get("is_addressable"):
            a["addressable"] += 1
        p = r.get("price_usd")
        if p and p > 0:
            a["gmv_usd"] += int(p)

    by_country = [{"country": k, **v} for k, v in sorted(agg.items(), key=lambda x: -x[1]["indexed"])]
    totals = {
        "countries": len(agg),
        "indexed": sum(v["indexed"] for v in agg.values()),
        "addressable": sum(v["addressable"] for v in agg.values()),
        "gmv_usd": sum(v["gmv_usd"] for v in agg.values()),
    }
    return {"totals": totals, "by_country": by_country}


# ════════════════════════════════════════════════════════════════════
# DIAGNOSTICO TEMPORAL v2 de paginacion crautos. Borrar al terminar.
# GET /diag/crautos  -> prueba si el campo 'l' del form pagina.
# ════════════════════════════════════════════════════════════════════

@app.get("/diag/crautos")
def diag_crautos():
    import re as _re

    BASE = "https://crautos.com/autosusados/"
    INDEX_URL = BASE + "index.cfm"
    SEARCH_URL = BASE + "searchresults.cfm"
    ID_RE = _re.compile(r"cardetail\.cfm\?c=(\d+)", _re.I)
    H = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept-Language": "es-CR,es;q=0.9",
        "Referer": INDEX_URL,
    }

    def ids_in(html):
        return sorted(set(ID_RE.findall(html or "")))

    out = {"diag_version": "v2-l-test"}
    with httpx.Client(follow_redirects=True, timeout=30, headers=H) as client:
        # cookie de sesion + leer el form
        r0 = client.get(INDEX_URL)
        tree = HTMLParser(r0.text)
        target = None
        for f in tree.css("form"):
            if "searchresults" in (f.attributes.get("action") or "").lower():
                target = f
                break
        if target is None:
            target = tree.css_first("form")

        payload = {}
        if target is not None:
            for sel in target.css("select"):
                n = sel.attributes.get("name")
                if n:
                    o = sel.css_first("option")
                    payload[n] = o.attributes.get("value", "") if o else ""
            for inp in target.css("input"):
                n = inp.attributes.get("name")
                ty = (inp.attributes.get("type") or "text").lower()
                if n and ty not in ("submit", "button", "image"):
                    payload[n] = inp.attributes.get("value", "")
        # coercion: None -> "" (como manda el navegador) y precio desde 0
        payload = {k: ("" if v is None else v) for k, v in payload.items()}
        payload["pricefrom"] = "0"
        out["payload"] = payload

        def post_with(field, value):
            p = dict(payload)
            p[field] = str(value)
            rr = client.post(SEARCH_URL, data=p)
            return ids_in(rr.text)

        # PRUEBA 1: el campo 'l' como numero de pagina
        l1 = post_with("l", 1)
        l2 = post_with("l", 2)
        l3 = post_with("l", 3)
        out["test_l"] = {
            "l1_count": len(l1), "l1_sample": l1[:3],
            "l2_count": len(l2), "l2_sample": l2[:3],
            "l3_count": len(l3), "l3_sample": l3[:3],
            "l2_nuevos_vs_l1": len(set(l2) - set(l1)),
            "l3_nuevos_vs_l2": len(set(l3) - set(l2)),
        }

        # PRUEBA 2: por si fuera 'p' via POST
        p1 = post_with("p", 1)
        p2 = post_with("p", 2)
        out["test_p"] = {
            "p1_count": len(p1), "p2_count": len(p2),
            "p2_nuevos_vs_p1": len(set(p2) - set(p1)),
        }

        # veredicto
        l_works = (set(l2) - set(l1)) and (set(l3) - set(l2))
        p_works = bool(set(p2) - set(p1))
        if l_works:
            out["veredicto"] = ("EL CAMPO 'l' PAGINA. httpx funciona re-POSTeando "
                                "el form con l=1,2,3... hasta que no haya autos nuevos.")
        elif p_works:
            out["veredicto"] = "El campo 'p' (via POST) pagina. Usar p++ en el POST."
        else:
            out["veredicto"] = ("Ni 'l' ni 'p' paginan via POST -> la paginacion es "
                                "por JavaScript -> usar Playwright.")

    return out



# ════════════════════════════════════════════════════════════════════
# INGESTA CRAUTOS EN DOS FASES (background, sin timeouts)
#   POST /inventory/crautos/discover  -> barre paginas, encola IDs (status=discovered)
#   POST /inventory/crautos/scrape    -> toma un lote discovered, baja detalle, status=scraped
#   GET  /inventory/crautos/status    -> conteos por estado + progreso de los jobs
# La cola es la misma tabla scraped_listings, usando la columna status.
# ════════════════════════════════════════════════════════════════════

CRAUTOS_JOBS = {
    "discover": {"running": False, "found": 0, "started": None, "finished": None, "error": None},
    "scrape": {"running": False, "done": 0, "errors": 0, "started": None, "finished": None, "error": None},
}


def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _crautos_record_from_detail(detail: dict, status: str) -> dict:
    """Mapea el dict de parse_detail a las columnas de scraped_listings.
    Mismo mapeo que /inventory-run/crautos + campos extra que crautos trae."""
    photos = []
    if detail.get("fotos"):
        photos = [p for p in detail["fotos"].split("|") if p]

    title = " ".join(str(x) for x in
                     [detail.get("marca"), detail.get("modelo"), detail.get("anio")] if x)
    make_v = detail.get("marca")
    model_v = detail.get("modelo")
    price_v = detail.get("precio_usd")
    year_v = detail.get("anio")
    km_v = detail.get("kilometraje")
    loc_v = detail.get("provincia")
    fuel_v = normalize_fuel(detail.get("combustible"))
    trans_v = normalize_transmission(detail.get("transmision"))
    primary = photos[0] if photos else None
    body_v = classify_body_type(model_v, title)
    qual = compute_quality_score(len(photos), price_v, year_v, km_v,
                                 make_v, model_v, loc_v, fuel_v, trans_v)
    now = _now_iso()

    return {
        "source": "crautos",
        "country": "cr",
        "url": detail.get("url"),
        "make": make_v,
        "model": model_v,
        "fuel_type": fuel_v,
        "transmission": trans_v,
        "title": title,
        "price_usd": price_v,
        "year": year_v,
        "km": km_v,
        "location": loc_v,
        "photos": photos,
        "photo_count": len(photos),
        "primary_photo": primary,
        "body_type": body_v,
        "quality_score": qual,
        "currency": detail.get("moneda_original"),
        "seller_phone": detail.get("vendedor_tel") or detail.get("vendedor_wa"),
        "scraped_at": now,
        "updated_at": now,
        "last_seen_at": now,
        "raw_payload": detail,
        "status": status,
    }


def _run_crautos_discover(delay: float, max_pages: int):
    job = CRAUTOS_JOBS["discover"]
    job.update(running=True, found=0, started=_now_iso(), finished=None, error=None)
    try:
        from .scrapers.crautos import crautos_scraper as crautos
        session = crautos.make_session()
        ids = crautos.collect_ids(session, delay, max_pages=max_pages)
        rows = [{"source": "crautos", "country": "cr",
                 "url": f"{crautos.DETAIL_URL}?c={cid}", "status": "discovered"}
                for cid in ids]
        # upsert por lotes, ignorando duplicados (no pisa filas ya scrapeadas)
        for i in range(0, len(rows), 500):
            supabase.table("scraped_listings").upsert(
                rows[i:i + 500], on_conflict="url", ignore_duplicates=True
            ).execute()
        job["found"] = len(rows)
    except Exception as e:
        job["error"] = str(e)
        log.exception("crautos discover failed")
    finally:
        job["running"] = False
        job["finished"] = _now_iso()


def _run_crautos_scrape(target: int, delay: float, chunk: int = 200):
    """Scrapea hasta `target` autos de la cola, en tandas de `chunk`,
    encadenando una tras otra hasta vaciar o llegar al objetivo.
    Cada auto se guarda al instante; si el proceso muere, lo ya hecho queda."""
    import time as _t
    job = CRAUTOS_JOBS["scrape"]
    job.update(running=True, done=0, errors=0, started=_now_iso(),
               finished=None, error=None, target=target)
    try:
        from .scrapers.crautos import crautos_scraper as crautos
        session = crautos.make_session()
        while job["done"] < target:
            faltan = target - job["done"]
            lote = min(chunk, faltan)
            res = (supabase.table("scraped_listings")
                   .select("url")
                   .eq("source", "crautos")
                   .eq("status", "discovered")
                   .limit(lote)
                   .execute())
            urls = [r["url"] for r in (res.data or [])]
            if not urls:
                job["note"] = "cola vacia, fin"
                break
            for url in urls:
                m = re.search(r"c=(\d+)", url or "")
                if not m:
                    job["errors"] += 1
                    continue
                cid = m.group(1)
                r = crautos.fetch(session, "GET", crautos.DETAIL_URL, params={"c": cid})
                if not r:
                    job["errors"] += 1
                    continue
                try:
                    detail = crautos.parse_detail(r.text, cid)
                    rec = _crautos_record_from_detail(detail, "staging")
                    supabase.table("scraped_listings").upsert(rec, on_conflict="url").execute()
                    job["done"] += 1
                except Exception:
                    job["errors"] += 1
                    log.exception("crautos scrape detail failed")
                _t.sleep(delay)
    except Exception as e:
        job["error"] = str(e)
        log.exception("crautos scrape failed")
    finally:
        job["running"] = False
        job["finished"] = _now_iso()


class CrautosDiscoverReq(BaseModel):
    delay: float = 1.0
    max_pages: int = 900


class CrautosScrapeReq(BaseModel):
    target: int = 13000   # cuantos scrapear en total esta corrida (encadena tandas)
    delay: float = 1.0


@app.post("/inventory/crautos/discover")
def crautos_discover(body: CrautosDiscoverReq, background_tasks: BackgroundTasks):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not connected.")
    if CRAUTOS_JOBS["discover"]["running"]:
        return {"status": "already_running", **CRAUTOS_JOBS["discover"]}
    background_tasks.add_task(_run_crautos_discover, body.delay, body.max_pages)
    return {"status": "started", "phase": "discover",
            "hint": "Corre en background ~10-13 min. Revisa GET /inventory/crautos/status"}


@app.post("/inventory/crautos/scrape")
def crautos_scrape(body: CrautosScrapeReq, background_tasks: BackgroundTasks):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not connected.")
    if CRAUTOS_JOBS["scrape"]["running"]:
        return {"status": "already_running", **CRAUTOS_JOBS["scrape"]}
    background_tasks.add_task(_run_crautos_scrape, body.target, body.delay)
    return {"status": "started", "phase": "scrape", "target": body.target,
            "hint": "Encadena tandas de 200 hasta llegar al target o vaciar la cola. "
                    "Segui el avance en GET /inventory/crautos/status"}


@app.get("/inventory/crautos/status")
def crautos_status():
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not connected.")

    def count(**filt):
        # count exacto sin head (compatible con esta version del cliente)
        q = (supabase.table("scraped_listings")
             .select("id", count="exact")
             .eq("source", "crautos")
             .limit(1))
        for k, v in filt.items():
            q = q.eq(k, v)
        return q.execute().count

    return {
        "discovered_pendientes": count(status="discovered"),
        "scraped": count(status="scraped"),
        "staging": count(status="staging"),
        "total_crautos": count(),
        "jobs": CRAUTOS_JOBS,
    }



# ════════════════════════════════════════════════════════════════════
# CARLY CONVERSACIONAL  (LLM + ranking sobre inventario real)
#   POST /carly/chat  -> recibe el historial, conversa, y cuando hay
#   perfil corre el ranking y devuelve las recomendaciones.
# Requiere: anthropic en requirements.txt y ANTHROPIC_API_KEY en el entorno.
# ════════════════════════════════════════════════════════════════════

from .carly_ranking import rank_cars, best_for_label
from .carly_profile import (
    CARLY_SYSTEM_PROMPT, extract_profile_json, profile_from_extraction,
)

try:
    from anthropic import Anthropic
    _anthropic = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]) \
        if os.environ.get("ANTHROPIC_API_KEY") else None
except Exception:
    _anthropic = None

CARLY_MODEL = "claude-sonnet-4-6"


class CarlyChatMessage(BaseModel):
    role: str          # "user" | "assistant"
    content: str


class CarlyChatRequest(BaseModel):
    messages: List[CarlyChatMessage]   # historial completo de la conversacion
    country: Optional[str] = None      # "cr" | "sv" para acotar inventario
    top_n: int = 4
    shown_cars: Optional[List[dict]] = None  # tarjetas que la persona YA tiene en
    # pantalla (el frontend las reenvia en turnos de seguimiento) para que Carly
    # pueda hablar de cualquiera sin contradecirse.


def _carly_inventory(profile, country=None, pool=600):
    """Trae un pool amplio de candidatos de Supabase aplicando solo los
    filtros DUROS baratos en SQL (pais, mensualidad, año). El ranking fino
    lo hace rank_cars en memoria sobre ese pool."""
    q = supabase.table("scraped_listings").select(CARLY_COLS).eq("status", "staging")
    if country:
        q = q.eq("country", country)
    if profile.max_monthly:
        q = q.lte("monthly_est", profile.max_monthly)
    if profile.max_price:
        q = q.lte("price_usd", profile.max_price)
    if profile.min_year:
        q = q.gte("year", profile.min_year)
    q = q.not_.is_("price_usd", "null").order("quality_score", desc=True)
    return q.limit(pool).execute().data or []


def _carly_card(entry):
    c = entry["car"]
    return {
        "make": c.get("make"), "model": c.get("model"), "year": c.get("year"),
        "price_usd": c.get("price_usd"), "monthly_est": c.get("monthly_est"),
        "km": c.get("km"), "body_type": c.get("body_type"),
        "transmission": c.get("transmission"), "location": c.get("location"),
        "primary_photo": c.get("primary_photo"), "url": c.get("url"),
        "score": entry["score"],
        "best_for": entry.get("best_for"),
        "factors": entry["factors"],
        "value_delta_pct": entry.get("value_delta_pct"),   # (7) fairness numerico
        "value_label": entry.get("value_label"),            # (7) fairness texto
        "caveat": entry.get("caveat"),                      # (8) contra honesta
        "inspect": entry.get("inspect"),                    # (9) que revisar
        "surprise": entry.get("surprise", False),
    }


@app.post("/carly/chat")
def carly_chat(body: CarlyChatRequest):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not connected.")
    if not _anthropic:
        raise HTTPException(status_code=500,
                            detail="ANTHROPIC_API_KEY no configurada en el entorno.")

    msgs = [{"role": m.role, "content": m.content} for m in body.messages]

    # On-screen context: if the person already has recommendation cards visible
    # (frontend echoes them back), tell Carly exactly which cars they are so she
    # can discuss ANY of them without claiming she "didn't recommend it".
    system_prompt = CARLY_SYSTEM_PROMPT
    if body.shown_cars:
        lines = []
        for c in body.shown_cars[:12]:
            vd = c.get("value_delta_pct")
            vtxt = f", {abs(vd):.0f}% {c.get('value_label','')}" if isinstance(vd, (int, float)) else ""
            lines.append(
                f"- {c.get('make')} {c.get('model')} {c.get('year')}, "
                f"${c.get('price_usd')} (${c.get('monthly_est')}/mes), "
                f"{c.get('km')} km, {c.get('body_type')}, {c.get('location')}{vtxt}"
            )
        system_prompt = (
            CARLY_SYSTEM_PROMPT
            + "\n\n# CARROS QUE LA PERSONA TIENE EN PANTALLA AHORA MISMO\n"
            "Estos son los autos que YA le mostraste y que ella esta viendo. "
            "Puedes y DEBES hablar de cualquiera de ellos con sus datos; JAMAS "
            "digas que no lo recomendaste o que no lo evaluaste: esta en tu lista.\n"
            + "\n".join(lines)
            + "\nSolo aclara 'ese no lo evalue' si preguntan por un modelo que NO "
            "aparece en esta lista."
        )

    # 1) Carly responde (conversa o emite el <PROFILE>)
    try:
        resp = _anthropic.messages.create(
            model=CARLY_MODEL,
            max_tokens=2048,
            system=system_prompt,
            messages=msgs,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e!s}")

    reply = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

    # 2) ¿hay perfil? si no, seguimos conversando
    data = extract_profile_json(reply)
    visible = re.sub(r"<PROFILE>.*?</PROFILE>", "", reply, flags=re.S)
    visible = re.sub(r"<PROFILE>.*$", "", visible, flags=re.S).strip()

    if not data:
        return {"phase": "conversation", "reply": visible}

    try:
        # 3) hay perfil -> ranking sobre inventario real
        profile = profile_from_extraction(data)
        country = body.country or (data.get("country") if isinstance(data, dict) else None)
        pool = _carly_inventory(profile, country=country)
        top = rank_cars(pool, profile, top_n=body.top_n)
        cards = [_carly_card(t) for t in top]
        relaxed_note = None

        if not cards:
            # Auto-relax: nunca dejar a la persona en un callejon sin salida.
            # Si exigieron una MARCA, la marca se mantiene y el presupuesto cede
            # (+25% -> +60% -> sin tope) antes de considerar abrir la marca.
            try:
                import copy as _copy
                req_brands = list(getattr(profile, "require_brands", None) or [])

                def _try(mult=None, uncapped=False, drop_body=False):
                    p2 = _copy.deepcopy(profile)
                    if uncapped:
                        p2.max_monthly = None
                        p2.max_price = None
                    elif mult:
                        if getattr(p2, "max_monthly", None):
                            p2.max_monthly = p2.max_monthly * mult
                        if getattr(p2, "max_price", None):
                            p2.max_price = p2.max_price * mult
                    if drop_body:
                        p2.require_body = []
                    pl = _carly_inventory(p2, country=country)
                    return rank_cars(pl, p2, top_n=body.top_n), pl

                top, pool2 = _try(mult=1.25)
                if top:
                    relaxed_note = "el presupuesto (~25% mas)"
                elif req_brands:
                    top, pool2 = _try(mult=1.6)
                    if top:
                        relaxed_note = ("el presupuesto, para conseguirte "
                                        + "/".join(req_brands))
                    else:
                        top, pool2 = _try(uncapped=True)
                        if top:
                            relaxed_note = ("el presupuesto por completo: estas son "
                                            "las unidades " + "/".join(req_brands)
                                            + " que existen ahora mismo")
                if not top and getattr(profile, "require_body", None):
                    top, pool2 = _try(mult=1.25, drop_body=True)
                    if top:
                        relaxed_note = "el tipo de carro"
                if top:
                    cards = [_carly_card(t) for t in top]
                    pool = pool2
            except Exception:
                pass

        if not cards:
            return {"phase": "recommendation",
                    "reply": ("No encontre opciones que calcen exacto, incluso "
                              "flexibilizando un poco. Dime que prefieres mover: "
                              "presupuesto, tipo de carro o año. Con uno solo que "
                              "sueltes te muestro opciones reales."),
                    "profile": data, "pool_size": len(pool),
                    "recommendations": [], "favorite": None}

        # 4) Carly explica los autos REALES (segunda pasada): el primer mensaje
        #    lo escribio antes de ver resultados. Ahora habla de lo que de verdad
        #    salio, mencionando el fairness y la contra honesta del favorito.
        fav = cards[0]
        resumen = "\n".join(
            f"- {c['make']} {c['model']} {c['year']}, ${c['monthly_est']}/mes, "
            f"mejor para {c['best_for']}"
            + (f", {abs(c['value_delta_pct']):.0f}% {c['value_label']}"
               if c.get("value_delta_pct") is not None else "")
            for c in cards
        )
        if relaxed_note:
            resumen += ("\n(NOTA INTERNA: no habia resultados con los criterios exactos; "
                        "estas opciones salieron al flexibilizar " + relaxed_note + ". "
                        "Presentalas con honestidad como alternativas cercanas, sin fingir "
                        "que cumplen el criterio original.)")
        fav_caveat = fav.get("caveat", "")
        closing_prompt = (
            "Acabas de recibir estas recomendaciones reales para la persona "
            f"(ya rankeadas):\n{resumen}\n\n"
            f"Tu favorita es la {fav['make']} {fav['model']} {fav['year']}. "
            f"Algo honesto que debe saber: {fav_caveat}\n\n"
            "Escribe tu VEREDICTO con voz de experta compradora, no de asistente. "
            "En este orden:\n"
            "1) Tu decision en primera persona: 'Yo compraria la X' con los 2-3 "
            "motivos concretos sacados de los datos de arriba (mensualidad, año, "
            "km, precio vs mercado).\n"
            "2) Lo que te haria dudar: el dato honesto, directo y sin suavizar.\n"
            "3) Tu lectura final en UNA frase, como amiga que sabe de carros: si "
            "su prioridad es X, la favorita gana; si en realidad le pesa mas Y, "
            "cual otra elegirias. Como AFIRMACION, no como pregunta.\n"
            "4) Cierra SIEMPRE con el siguiente paso concreto dentro de CarTrade, "
            "como invitacion directa (no pregunta). Ejemplo: 'Toca Ver detalles "
            "en la favorita y desde ahi inicias la compra verificada: inspeccion, "
            "papeles, custodia y financiamiento van por nuestra cuenta.' Adapta "
            "la frase con naturalidad, pero el CTA siempre apunta a una accion "
            "en CarTrade (ver detalles, comparar lado a lado, o iniciar la "
            "compra verificada). Nunca termines sin proponer ese paso.\n"
            f"Incluye en alguna parte UNA frase de procedencia con el numero real: "
            f"'de los {len(pool)} que cumplen tus criterios, estas son mis mejores apuestas'. "
            "Maximo 7 frases en total, sin titulos ni encabezados. "
            "Se firme con lo que los datos muestran y explicita que el estado "
            "mecanico real lo confirma la inspeccion. NO inventes porcentajes de "
            "confianza ni datos que no esten arriba. NO hagas preguntas. NO "
            "repitas la tabla (la persona ya la ve). NO emitas bloque PROFILE."
        )
        try:
            resp2 = _anthropic.messages.create(
                model=CARLY_MODEL, max_tokens=400, system=system_prompt,
                messages=msgs + [
                    {"role": "assistant", "content": visible or "Tengo tus opciones."},
                    {"role": "user", "content": closing_prompt},
                ],
            )
            closing = "".join(b.text for b in resp2.content
                              if getattr(b, "type", "") == "text").strip()
            closing = re.sub(r"<PROFILE>.*?</PROFILE>", "", closing, flags=re.S).strip()
        except Exception:
            closing = visible  # si la segunda pasada falla, usamos la primera

        return {
            "phase": "recommendation",
            "reply": closing or visible,
            "profile": data,
            "pool_size": len(pool),
            "recommendations": cards,
            "favorite": fav,
        }
    except Exception as _diag_e:
        import traceback as _tb
        print(_tb.format_exc())
        return {"phase": "conversation",
                "reply": "[DIAG] " + type(_diag_e).__name__ + ": " + str(_diag_e)[:300]}
