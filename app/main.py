"""CarTrade link resolver — FastAPI entry point.

POST /resolve-link
GET  /health
"""
from __future__ import annotations
import os
import time
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl, ValidationError

from . import cache, rate_limit, platforms
from .resolvers import encuentra24, olx, facebook, mercadolibre, fallback
from .resolvers.base import Listing

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("resolver")


# Health tracking — last result per platform
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
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — production allows cartrade.live; dev allows everything.
CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "https://cartrade.live,https://www.cartrade.live"
).split(",")

# In dev mode (no env var or explicitly set), allow all origins
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


@app.get("/")
async def root():
    return {
        "service": "cartrade-resolver",
        "version": "1.0.0",
        "endpoints": ["POST /resolve-link", "GET /health"],
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
    }


def _client_ip(req: Request) -> str:
    # Railway/Fly set x-forwarded-for; fall back to client.host
    xff = req.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return req.client.host if req.client else "unknown"


@app.post("/resolve-link")
async def resolve_link(body: ResolveRequest, request: Request):
    url = str(body.url)
    ip = _client_ip(request)

    # ─── Rate limit ──────────────────────────────────────────────
    allowed, remaining = rate_limit.check(ip)
    if not allowed:
        log.warning("rate limit hit ip=%s", ip)
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    # ─── Validate URL is from a whitelisted domain ───────────────
    if not platforms.is_allowed(url):
        log.info("rejected non-whitelisted url=%s ip=%s", url, ip)
        raise HTTPException(
            status_code=400,
            detail="URL is not from a supported listing platform.")

    # ─── Cache check ─────────────────────────────────────────────
    cached = cache.get(url)
    if cached:
        cached["cached"] = True
        log.info("cache hit url=%s ip=%s", url, ip)
        return cached

    # ─── Dispatch to resolver ───────────────────────────────────
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

    # Health tracking
    has_essentials = listing.title is not None or len(listing.photos) > 0
    _record(platform, ok=has_essentials and not listing.errors,
            error="; ".join(listing.errors)[:200] if listing.errors else None)

    payload = listing.to_dict()
    payload["elapsed_seconds"] = round(elapsed, 2)

    # Cache it (don't cache total failures)
    if has_essentials:
        cache.put(url, payload)

    return payload
