"""CarTrade link resolver — FastAPI entry point.

POST /resolve-link
POST /inventory-run
GET  /inventory-preview
GET  /health
"""
from __future__ import annotations

import os
import re
import time
import logging
import httpx
from typing import Optional
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache.init_db()
    yield


app = FastAPI(title="CarTrade Link Resolver", version="1.4.0", lifespan=lifespan)

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


@app.get("/")
async def root():
    return {
        "service": "cartrade-resolver",
        "version": "1.4.0",
        "endpoints": ["POST /resolve-link", "POST /inventory-run", "GET /inventory-preview", "GET /health"],
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


@app.post("/inventory-run")
async def inventory_run(body: InventoryRunRequest):
    country = body.country.lower().strip()

    if country not in COUNTRY_SEARCH_URLS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported country. Use one of: {', '.join(COUNTRY_SEARCH_URLS.keys())}"
        )

    if body.pages < 1 or body.pages > 50:
        raise HTTPException(status_code=400, detail="Pages must be between 1 and 50.")

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
                db_record = {
                    "source": "encuentra24",
                    "country": country,
                    "url": url,
                    "make": field_value(payload, "make"),
                    "model": field_value(payload, "model"),
                    "fuel_type": fuel_value,
                    "transmission": transmission_value,
                    "title": title_value,
                    "price_usd": field_value(payload, "price_usd"),
                    "year": field_value(payload, "year"),
                    "km": field_value(payload, "km"),
                    "location": field_value(payload, "location"),
                    "photos": cleaned_photos,
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

    if has_essentials:
        cache.put(url, payload)

    return payload
