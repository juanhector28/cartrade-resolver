"""SQLite-backed cache, keyed by URL hash. TTL configurable."""
from __future__ import annotations
import sqlite3
import hashlib
import json
import time
import os
from typing import Optional
from contextlib import contextmanager

CACHE_DB = os.environ.get("CACHE_DB", "/data/resolver_cache.db")
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", str(7 * 24 * 3600)))  # 7 days


def _ensure_dir():
    d = os.path.dirname(CACHE_DB)
    if d and not os.path.exists(d):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass


@contextmanager
def _conn():
    _ensure_dir()
    c = sqlite3.connect(CACHE_DB)
    try:
        yield c
    finally:
        c.close()


def init_db():
    """Create cache table if it doesn't exist."""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                payload TEXT NOT NULL,
                stored_at INTEGER NOT NULL
            )
        """)
        c.commit()


def _key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def get(url: str) -> Optional[dict]:
    """Return cached payload if fresh, else None."""
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT payload, stored_at FROM cache WHERE key = ?",
                (_key(url),)
            ).fetchone()
            if not row:
                return None
            payload, stored_at = row
            if time.time() - stored_at > CACHE_TTL_SECONDS:
                return None  # stale
            return json.loads(payload)
    except (sqlite3.Error, json.JSONDecodeError):
        return None


def put(url: str, payload: dict) -> None:
    """Store payload under URL hash."""
    try:
        with _conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO cache (key, url, payload, stored_at) VALUES (?, ?, ?, ?)",
                (_key(url), url, json.dumps(payload), int(time.time()))
            )
            c.commit()
    except (sqlite3.Error, TypeError):
        pass  # cache failures should not break the resolver
