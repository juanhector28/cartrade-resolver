from __future__ import annotations

from pathlib import Path

APP = Path("/app/app")
if not APP.exists():
    raise RuntimeError("Resolver test patch must run inside built Resolver image")

clock_code = r'''
from __future__ import annotations
import json
import os
import time as _time
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_EPOCH = 1788220800.0


def epoch() -> float:
    if os.getenv("ATLAS_TEST_ENV") != "1":
        return _time.time()
    path = Path(os.getenv("ATLAS_TEST_CLOCK_PATH", "/test-clock/clock.json"))
    try:
        return float(json.loads(path.read_text(encoding="utf-8"))["epoch"])
    except Exception:
        return _DEFAULT_EPOCH


def now() -> datetime:
    return datetime.fromtimestamp(epoch(), tz=timezone.utc)


def now_iso() -> str:
    return now().isoformat()
'''
(APP / "test_clock.py").write_text(clock_code, encoding="utf-8")

runner = APP / "atlas_manifest_runner.py"
rs = runner.read_text(encoding="utf-8")
old = 'def _now_iso() -> str:\n    return datetime.now(timezone.utc).isoformat()\n'
if old not in rs:
    raise RuntimeError("AtlasManifestRunner _now_iso anchor missing")
rs = rs.replace(
    old,
    'def _now_iso() -> str:\n'
    '    if os.getenv("ATLAS_TEST_ENV") == "1":\n'
    '        from .test_clock import now_iso\n'
    '        return now_iso()\n'
    '    return datetime.now(timezone.utc).isoformat()\n',
    1,
)
runner.write_text(rs, encoding="utf-8")

main = APP / "main.py"
s = main.read_text(encoding="utf-8")
if "# ATLAS_RESOLVER_RED_HARNESS_V11" not in s:
    s += r'''

# ATLAS_RESOLVER_RED_HARNESS_V11
if os.getenv("ATLAS_TEST_ENV") == "1":
    import json as _atlas_test_json
    import httpx as _atlas_test_httpx
    from fastapi import Header as _AtlasTestHeader
    from fastapi.responses import JSONResponse as _AtlasTestJSONResponse
    from .test_clock import now_iso as _atlas_test_now_iso

    def _atlas_test_require(
        x_atlas_test_token: str | None = _AtlasTestHeader(default=None, alias="X-Atlas-Test-Token")
    ):
        expected = os.getenv("ATLAS_TEST_TOKEN") or ""
        if not expected or x_atlas_test_token != expected:
            raise HTTPException(status_code=401, detail="invalid atlas test token")
        return True

    def _atlas_provenance(row):
        raw = row.get("raw_payload") if isinstance(row, dict) else None
        atlas = (raw or {}).get("atlas") if isinstance(raw, dict) else None
        if isinstance(atlas, dict) and atlas.get("source_id"):
            return {
                "source_id": atlas.get("source_id"),
                "manifest_version": atlas.get("manifest_version"),
            }
        return {
            "source_id": row.get("source") if isinstance(row, dict) else None,
            "manifest_version": None,
        }

    def _atlas_decorate_payload(data):
        if not isinstance(data, (dict, list)) or not supabase:
            return data
        targets = []
        def walk(node):
            if isinstance(node, dict):
                if node.get("url"):
                    targets.append(node)
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(data)
        urls = sorted({str(x.get("url")) for x in targets if x.get("url")})
        meta = {}
        for url in urls:
            try:
                rows = (
                    supabase.table("scraped_listings")
                    .select("url,source,raw_payload")
                    .eq("url", url).limit(1).execute().data or []
                )
                if rows:
                    meta[url] = _atlas_provenance(rows[0])
            except Exception:
                continue
        for item in targets:
            p = meta.get(str(item.get("url")))
            if p:
                item["source_id"] = p.get("source_id")
                item["manifest_version"] = p.get("manifest_version")
        return data

    @app.middleware("http")
    async def _atlas_test_provenance_contract(request, call_next):
        response = await call_next(request)
        if request.url.path not in {"/carly/search", "/carly/chat"}:
            return response
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        try:
            data = _atlas_test_json.loads(body.decode("utf-8"))
        except Exception:
            return _AtlasTestJSONResponse(
                content={"error": "test provenance middleware could not decode Carly response"},
                status_code=500,
            )
        data = _atlas_decorate_payload(data)
        return _AtlasTestJSONResponse(content=data, status_code=response.status_code)

    @app.get("/atlas-test/preflight", dependencies=[Depends(_atlas_test_require)])
    async def atlas_test_preflight():
        base = (os.getenv("ATLAS_FIXTURE_BASE_URL") or "").rstrip("/")
        if not base:
            raise HTTPException(status_code=409, detail="ATLAS_FIXTURE_BASE_URL missing")
        async with _atlas_test_httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            result = await client.get(base + "/health")
        ok = result.status_code == 200 and bool(result.json().get("ok"))
        if not ok:
            raise HTTPException(status_code=409, detail="fixture host unreachable from Resolver")
        return {"ok": True, "fixture": True, "supabase": supabase is not None}

    @app.post("/atlas-test/truncate", dependencies=[Depends(_atlas_test_require)])
    def atlas_test_truncate():
        if not supabase:
            raise HTTPException(status_code=503, detail="Supabase not connected")
        rows = supabase.table("scraped_listings").select("id").limit(10000).execute().data or []
        deleted = 0
        for row in rows:
            supabase.table("scraped_listings").delete().eq("id", row["id"]).execute()
            deleted += 1
        return {"ok": True, "deleted": deleted}

    @app.post("/atlas-test/seed-production", dependencies=[Depends(_atlas_test_require)])
    def atlas_test_seed_production(url: str):
        if not supabase:
            raise HTTPException(status_code=503, detail="Supabase not connected")
        now = _atlas_test_now_iso()
        record = {
            "source": "manual-source",
            "country": "gt",
            "url": url,
            "title": "AtlasFixture GoldenDOM 2024 Manual Sentinel",
            "make": "AtlasFixture",
            "model": "GoldenDOM",
            "year": 2024,
            "km": 123456,
            "price_usd": 9999,
            "currency": "USD",
            "fuel_type": "Gasolina",
            "transmission": "Automática",
            "location": "Guatemala",
            "photos": [],
            "photo_count": 0,
            "primary_photo": None,
            "body_type": "sedan",
            "quality_score": 90,
            "monthly_est": 250,
            "raw_payload": {"fixture": "production-sentinel"},
            "scraped_at": now,
            "updated_at": now,
            "last_seen_at": now,
            "status": "staging",
            "listing_state": "indexed",
        }
        supabase.table("scraped_listings").upsert(record, on_conflict="url").execute()
        return atlas_test_snapshot(url)

    @app.get("/atlas-test/snapshot", dependencies=[Depends(_atlas_test_require)])
    def atlas_test_snapshot(url: str):
        if not supabase:
            raise HTTPException(status_code=503, detail="Supabase not connected")
        rows = supabase.table("scraped_listings").select("*").eq("url", url).limit(1).execute().data or []
        return {"row": rows[0] if rows else None}

    @app.get("/atlas-test/shadow-records", dependencies=[Depends(_atlas_test_require)])
    def atlas_test_shadow_records(source_id: str, manifest_version: int | None = None):
        if not supabase:
            raise HTTPException(status_code=503, detail="Supabase not connected")
        rows = (
            supabase.table("scraped_listings")
            .select("*")
            .eq("status", "atlas_shadow")
            .contains("raw_payload", {"atlas": {"source_id": source_id}})
            .limit(500).execute().data or []
        )
        if manifest_version is not None:
            rows = [
                row for row in rows
                if ((row.get("raw_payload") or {}).get("atlas") or {}).get("manifest_version") == manifest_version
            ]
        safe = []
        for row in rows:
            p = _atlas_provenance(row)
            safe.append({
                "id": row.get("id"),
                "url": row.get("url"),
                "status": row.get("status"),
                "make": row.get("make"),
                "model": row.get("model"),
                "year": row.get("year"),
                "price_usd": row.get("price_usd"),
                **p,
            })
        return {"count": len(safe), "records": safe}

    @app.post("/atlas-test/reset-shadow", dependencies=[Depends(_atlas_test_require)])
    def atlas_test_reset_shadow(source_id: str):
        if not supabase:
            raise HTTPException(status_code=503, detail="Supabase not connected")
        rows = (
            supabase.table("scraped_listings")
            .select("id,status,raw_payload")
            .eq("status", "atlas_shadow")
            .contains("raw_payload", {"atlas": {"source_id": source_id}})
            .limit(5000).execute().data or []
        )
        deleted = 0
        for row in rows:
            atlas = ((row.get("raw_payload") or {}).get("atlas") or {})
            if row.get("status") != "atlas_shadow" or atlas.get("source_id") != source_id:
                continue
            supabase.table("scraped_listings").delete().eq("id", row["id"]).eq("status", "atlas_shadow").execute()
            deleted += 1
        return {"ok": True, "source_id": source_id, "deleted": deleted}
'''
    main.write_text(s, encoding="utf-8")

print("Installed Resolver red-harness v1.1 test surface")
