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
import sqlite3
import logging
import httpx
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
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
async def inventory_run_crautos(body: CrautosInventoryRunRequest):
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
    country = body.country.lower().strip()

    if country not in COUNTRY_SEARCH_URLS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported country. Use one of: {', '.join(COUNTRY_SEARCH_URLS.keys())}"
        )

    if body.pages < 1 or body.pages > 200:
        raise HTTPException(status_code=400, detail="Pages must be between 1 and 200.")

    search_url = COUNTRY_SEARCH_URLS[country]
    discovered_urls = set()
    page_debug = []

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "es;q=0.9"},
    ) as cli:
        for page in range(1, body.pages + 1):
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
                    "year": year_value,
                    "km": km_value,
                    "location": location_value,
                    "photos": cleaned_photos,
                    "photo_count": len(cleaned_photos),       # added
                    "primary_photo": photo,                    # added
                    "body_type": body_type_value,              # added
                    "quality_score": quality_value,            # added
                    "raw_payload": payload,
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
        "pages": body.pages,
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
    if cached:
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

    if has_essentials:
        cache.put(url, payload)

    return payload


@app.post("/carly/search")
async def carly_search(body: CarlySearchRequest):
    """Carly: parse a Spanish query, match the live inventory, rank, and return top N."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not connected.")

    it = parse_intent(body.q)
    q = supabase.table("scraped_listings").select(CARLY_COLS)

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

    if it.use == "primer":
        q = q.order("price_usd", desc=False).order("quality_score", desc=True)
    elif it.newest_first:
        q = q.order("year", desc=True).order("quality_score", desc=True)
    else:
        q = q.order("quality_score", desc=True).order("year", desc=True)

    limit = max(1, min(body.limit, 12))
    try:
        rows = q.limit(limit).execute().data or []
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Supabase query failed: {e!s}")

    results = []
    for i, car in enumerate(rows):
        results.append({
            **{k: car.get(k) for k in (
                "id", "country", "url", "make", "model", "year", "km", "price_usd",
                "monthly_est", "transmission", "location", "body_type",
                "quality_score", "primary_photo",
            )},
            "tag": TAGS[i] if i < len(TAGS) else "Opción",
            "why": build_why(car, it),
        })

    return {"query": body.q, "intent": it.model_dump(), "count": len(results), "results": results}


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
