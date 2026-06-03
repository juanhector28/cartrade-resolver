"""CarTrade link resolver — FastAPI entry point.

POST /resolve-link
POST /inventory-run
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

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("resolver")


SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

supabase = None

if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    log.info("Supabase connected.")
else:
    log.warning("Supabase env vars missing.")


_health: dict[str, dict] = {
    "encuentra24": {"last_ok": None, "last_error": None, "last_at": None},
    "olx":         {"last_ok": None, "last_error": None, "last_at": None},
    "facebook":    {"last_ok": None, "last_error": None, "last_at": None},
    "mercadolibre":{"last_ok": None, "last_error": None, "last_at": None},
}


def _record(platform: str, ok: bool, error: Optional[str] = None):
    h = _health.get(platform)
    if h is not None:
        h["last_at"] = int(time.time())
        if ok:
            h["last_ok"] = int(time.time())
            h["last_error"] = None
        else:
            h["last_error"] = error


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache.init_db()
    log.info("Resolver started. Cache DB: %s", cache.CACHE_DB)
    yield
    log.info("Resolver shutting down.")


app = FastAPI(
    title="CarTrade Link Resolver",
    version="1.2.0",
    lifespan=lifespan,
)

CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "https://cartrade.live,https://www.cartrade.live"
).split(",")

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
        "version": "1.2.0",
        "endpoints": ["POST /resolve-link", "POST /inventory-run", "GET /health"],
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


@app.post("/inventory-run")
async def inventory_run(body: InventoryRunRequest):
    if body.country != "sv":
        raise HTTPException(status_code=400, detail="Only sv is supported for this test.")

    if body.pages < 1 or body.pages > 5:
        raise HTTPException(status_code=400, detail="For this test, pages must be between 1 and 5.")

    search_url = "https://www.encuentra24.com/el-salvador-es/autos-usados"
    discovered_urls = set()

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "es-SV,es;q=0.9",
        },
    ) as cli:
        for page in range(1, body.pages + 1):
            page_url = f"{search_url}?page={page}"
            log.info("inventory discovering page=%s url=%s", page, page_url)

            r = await cli.get(page_url)
            r.raise_for_status()

            tree = HTMLParser(r.text)

            for node in tree.css("a[href]"):
                href = node.attributes.get("href", "")

                if "/autos-usados/" not in href:
                    continue

                if href.startswith("/"):
                    href = "https://www.encuentra24.com" + href

                href = href.split("?")[0]

                if re.search(r"/\d+$", href):
                    discovered_urls.add(href)

    results = []
    saved_count = 0
    error_count = 0

    for i, url in enumerate(sorted(discovered_urls), start=1):
        log.info("inventory resolving %s/%s url=%s", i, len(discovered_urls), url)

        try:
            listing = await encuentra24.resolve(url)
            payload = listing.to_dict()

            payload["inventory_source"] = "encuentra24"
            payload["inventory_country"] = "sv"
            payload["inventory_scraped_at"] = int(time.time())

            results.append(payload)

            if supabase:
                db_record = {
                    "source": "encuentra24",
                    "country": "sv",
                    "url": url,
                    "title": (
                        payload.get("title", {}).get("value")
                        if isinstance(payload.get("title"), dict)
                        else None
                    ),
                    "price_usd": (
                        payload.get("price_usd", {}).get("value")
                        if isinstance(payload.get("price_usd"), dict)
                        else None
                    ),
                    "year": (
                        payload.get("year", {}).get("value")
                        if isinstance(payload.get("year"), dict)
                        else None
                    ),
                    "km": (
                        payload.get("km", {}).get("value")
                        if isinstance(payload.get("km"), dict)
                        else None
                    ),
                    "location": (
                        payload.get("location", {}).get("value")
                        if isinstance(payload.get("location"), dict)
                        else None
                    ),
                    "photos": payload.get("photos", []),
                    "raw_payload": payload,
                    "status": "staging",
                }

                supabase.table("scraped_listings").upsert(
                    db_record,
                    on_conflict="url"
                ).execute()

                saved_count += 1

        except Exception as e:
            error_count += 1
            log.exception("inventory resolver error url=%s", url)

            results.append({
                "url": url,
                "error": str(e),
                "inventory_source": "encuentra24",
                "inventory_country": "sv",
                "inventory_scraped_at": int(time.time()),
            })

        time.sleep(0.5)

    return {
        "country": body.country,
        "pages": body.pages,
        "discovered_count": len(discovered_urls),
        "resolved_count": len(results),
        "saved_count": saved_count,
        "error_count": error_count,
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
        log.warning("rate limit hit ip=%s", ip)
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    if not platforms.is_allowed(url):
        log.info("rejected non-whitelisted url=%s ip=%s", url, ip)
        raise HTTPException(
            status_code=400,
            detail="URL is not from a supported listing platform.")

    cached = cache.get(url)
    if cached:
        cached["cached"] = True
        log.info("cache hit url=%s ip=%s", url, ip)
        return cached

    platform = platforms.detect(url)
    log.info("resolving platform=%s url=%s ip=%s remaining=%d", platform, url, ip, remaining)

    started = time.time()
    listing: Listing

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
        log.exception("resolver crashed url=%s", url)
        _record(platform, ok=False, error=str(e)[:200])
        raise HTTPException(status_code=500, detail=f"Resolver error: {e!s}")

    elapsed = time.time() - started
    log.info("resolved platform=%s elapsed=%.2fs errors=%d photos=%d",
             platform, elapsed, len(listing.errors), len(listing.photos))

    has_essentials = listing.title is not None or len(listing.photos) > 0
    _record(platform, ok=has_essentials and not listing.errors,
            error="; ".join(listing.errors)[:200] if listing.errors else None)

    payload = listing.to_dict()
    payload["elapsed_seconds"] = round(elapsed, 2)

    if has_essentials:
        cache.put(url, payload)

    return payload
