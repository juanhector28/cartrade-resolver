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


def infer_fuel_from_text(text: str | None):
    if not text:
        return None
    t = text.lower()
    if "diesel" in t:
        return "Diesel"
    if "gasolina" in t:
        return "Gasoline"
    if "híbrido" in t or "hibrido" in t or "hybrid" in t:
        return "Hybrid"
    if "eléctrico" in t or "electrico" in t or "electric" in t:
        return "Electric"
    return None


def infer_transmission_from_text(text: str | None):
    if not text:
        return None
    t = text.lower()
    if "manual" in t:
        return "Manual"
    if "automático" in t or "automatica" in t or "automática" in t or "automatico" in t or "automatic" in t:
        return "Automatic"
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache.init_db()
    yield


app = FastAPI(title="CarTrade Link Resolver", version="1.3.4", lifespan=lifespan)

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
        "version": "1.3.4",
        "endpoints": ["POST /resolve-link", "POST /inventory-run", "GET /inventory-preview", "GET /health"],
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
async def inventory_preview(limit: int = 20):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not connected.")
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 100.")

    response = (
        supabase
        .table("scraped_listings")
        .select("*")
        .order("scraped_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"count": len(response.data), "items": response.data}


@app.post("/inventory-run")
async def inventory_run(body: InventoryRunRequest):
    if body.country != "sv":
        raise HTTPException(status_code=400, detail="Only sv is supported for this test.")
    if body.pages < 1 or body.pages > 34:
        raise HTTPException(status_code=400, detail="For this test, pages must be between 1 and 34.")

    search_url = "https://www.encuentra24.com/el-salvador-es/autos-usados"
    discovered_urls = set()
    page_debug = []

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "es-SV,es;q=0.9"},
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

    for i, url in enumerate(sorted(discovered_urls), start=1):
        try:
            listing = await encuentra24.resolve(url)
            payload = listing.to_dict()

            title_value = field_value(payload, "title")
            description_value = field_value(payload, "description")
            text_for_inference = f"{title_value or ''} {description_value or ''}"

            fuel_value = field_value(payload, "fuel")
            transmission_value = field_value(payload, "transmission")

            payload["inventory_source"] = "encuentra24"
            payload["inventory_country"] = "sv"
            payload["inventory_scraped_at"] = int(time.time())

            if supabase:
                db_record = {
                    "source": "encuentra24",
                    "country": "sv",
                    "url": url,
                    "make": field_value(payload, "make"),
                    "model": field_value(payload, "model"),
                    "fuel_type": fuel_value or infer_fuel_from_text(text_for_inference),
                    "transmission": transmission_value or infer_transmission_from_text(text_for_inference),
                    "title": title_value,
                    "price_usd": field_value(payload, "price_usd"),
                    "year": field_value(payload, "year"),
                    "km": field_value(payload, "km"),
                    "location": field_value(payload, "location"),
                    "photos": payload.get("photos", []),
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
        "country": body.country,
        "pages": body.pages,
        "discovered_count": len(discovered_urls),
        "resolved_count": len(discovered_urls),
        "saved_count": saved_count,
        "error_count": error_count,
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
