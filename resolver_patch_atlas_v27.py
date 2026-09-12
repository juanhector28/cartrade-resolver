from pathlib import Path

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
marker = '# ATLAS_RUN_SOURCE_ASYNC_V27'

if marker not in s:
    s += r'''

# ATLAS_RUN_SOURCE_ASYNC_V27
import asyncio as _atlas_job_asyncio
import os as _atlas_job_os
import uuid as _atlas_job_uuid
from datetime import datetime as _atlas_job_datetime, timezone as _atlas_job_timezone
from fastapi import Header as _AtlasJobHeader, HTTPException as _AtlasJobHTTPException
from fastapi.responses import JSONResponse as _AtlasJobJSONResponse
from pydantic import BaseModel as _AtlasJobBaseModel, Field as _AtlasJobField

_ATLAS_JOB_TABLE = "atlas_runtime_jobs"
_ATLAS_JOB_RUNNING = set()
_ATLAS_JOB_STALE_SECONDS = max(300, int(_atlas_job_os.getenv("ATLAS_RUNTIME_JOB_STALE_SECONDS", "900")))
_ATLAS_JOB_HEARTBEAT_SECONDS = max(10, int(_atlas_job_os.getenv("ATLAS_RUNTIME_JOB_HEARTBEAT_SECONDS", "30")))


class AtlasManifestJobRequest(AtlasManifestRunRequest):
    idempotency_key: str = _AtlasJobField(min_length=8, max_length=500)


def _atlas_job_now():
    return _atlas_job_datetime.now(_atlas_job_timezone.utc)


def _atlas_job_now_iso():
    return _atlas_job_now().isoformat()


def _atlas_job_parse_dt(value):
    if not value:
        return None
    try:
        return _atlas_job_datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _atlas_job_require_token(x_atlas_token):
    _require_atlas_bridge_token(x_atlas_token)


def _atlas_job_public(row):
    row = dict(row or {})
    return {
        "job_id": row.get("job_id"),
        "idempotency_key": row.get("idempotency_key"),
        "operation": row.get("operation"),
        "source_id": row.get("source_id"),
        "manifest_version": row.get("manifest_version"),
        "state": row.get("state"),
        "attempt_count": int(row.get("attempt_count") or 0),
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "heartbeat_at": row.get("heartbeat_at"),
        "completed_at": row.get("completed_at"),
        "updated_at": row.get("updated_at"),
        "result": row.get("result") if row.get("state") == "succeeded" else None,
        "error": row.get("error") if row.get("state") == "failed" else None,
    }


def _atlas_job_by_id(job_id):
    rows = (
        supabase.table(_ATLAS_JOB_TABLE)
        .select("job_id,idempotency_key,operation,source_id,manifest_version,state,request,result,error,attempt_count,claim_token,created_at,started_at,heartbeat_at,completed_at,updated_at")
        .eq("job_id", str(job_id))
        .limit(1)
        .execute().data or []
    )
    return dict(rows[0]) if rows else None


def _atlas_job_by_key(idempotency_key):
    rows = (
        supabase.table(_ATLAS_JOB_TABLE)
        .select("job_id,idempotency_key,operation,source_id,manifest_version,state,request,result,error,attempt_count,claim_token,created_at,started_at,heartbeat_at,completed_at,updated_at")
        .eq("idempotency_key", str(idempotency_key))
        .limit(1)
        .execute().data or []
    )
    return dict(rows[0]) if rows else None


def _atlas_job_validate_request(req):
    if req.mode != "shadow":
        raise _AtlasJobHTTPException(status_code=422, detail="async runner only permits mode=shadow")
    if len((req.country or "").strip()) != 2:
        raise _AtlasJobHTTPException(status_code=422, detail="country must be a two-letter code")
    if not req.source_id.startswith(req.country.lower() + "-"):
        raise _AtlasJobHTTPException(status_code=422, detail="source_id/country mismatch")
    base_url = str((req.manifest or {}).get("base_url") or "")
    domain = (req.domain or "").strip().lower()
    if not domain and base_url:
        from urllib.parse import urlparse as _atlas_job_urlparse
        domain = _atlas_job_urlparse(base_url).netloc.lower().removeprefix("www.")
    if not domain:
        raise _AtlasJobHTTPException(status_code=422, detail="domain is required")
    if req.persist and not supabase:
        raise _AtlasJobHTTPException(status_code=503, detail="Supabase is not connected")
    return domain


async def _atlas_job_heartbeat(job_id, claim_token):
    try:
        while True:
            await _atlas_job_asyncio.sleep(_ATLAS_JOB_HEARTBEAT_SECONDS)
            now = _atlas_job_now_iso()
            supabase.table(_ATLAS_JOB_TABLE).update({
                "heartbeat_at": now,
                "updated_at": now,
            }).eq("job_id", str(job_id)).eq("claim_token", claim_token).eq("state", "running").execute()
    except _atlas_job_asyncio.CancelledError:
        raise


async def _atlas_job_execute(job_id):
    job_id = str(job_id)
    if job_id in _ATLAS_JOB_RUNNING:
        return
    _ATLAS_JOB_RUNNING.add(job_id)
    heartbeat_task = None
    try:
        row = _atlas_job_by_id(job_id)
        if not row or row.get("state") != "queued":
            return

        claim_token = _atlas_job_uuid.uuid4().hex
        now = _atlas_job_now_iso()
        supabase.table(_ATLAS_JOB_TABLE).update({
            "state": "running",
            "claim_token": claim_token,
            "started_at": row.get("started_at") or now,
            "heartbeat_at": now,
            "updated_at": now,
            "attempt_count": int(row.get("attempt_count") or 0) + 1,
            "error": None,
        }).eq("job_id", job_id).eq("state", "queued").is_("claim_token", "null").execute()

        claimed = _atlas_job_by_id(job_id)
        if not claimed or claimed.get("state") != "running" or claimed.get("claim_token") != claim_token:
            return

        request_data = dict(claimed.get("request") or {})
        req = AtlasManifestRunRequest(**request_data)
        domain = _atlas_job_validate_request(req)
        heartbeat_task = _atlas_job_asyncio.create_task(_atlas_job_heartbeat(job_id, claim_token))

        result = await _atlas_manifest_runner.run(
            source_id=req.source_id,
            country=req.country,
            domain=domain,
            manifest=req.manifest,
            manifest_version=req.manifest_version,
            limit=req.limit,
            scan_limit=req.scan_limit,
            persist=req.persist,
        )
        done = _atlas_job_now_iso()
        supabase.table(_ATLAS_JOB_TABLE).update({
            "state": "succeeded",
            "result": result,
            "error": None,
            "heartbeat_at": done,
            "completed_at": done,
            "updated_at": done,
        }).eq("job_id", job_id).eq("claim_token", claim_token).eq("state", "running").execute()
        print("ATLAS_RUNTIME_JOB_TERMINAL=" + str({
            "job_id": job_id,
            "source_id": req.source_id,
            "state": "succeeded",
        }), flush=True)
    except Exception as exc:
        try:
            failed = _atlas_job_now_iso()
            current = _atlas_job_by_id(job_id) or {}
            token = current.get("claim_token")
            q = supabase.table(_ATLAS_JOB_TABLE).update({
                "state": "failed",
                "error": str(exc)[:4000],
                "heartbeat_at": failed,
                "completed_at": failed,
                "updated_at": failed,
            }).eq("job_id", job_id).eq("state", "running")
            if token:
                q = q.eq("claim_token", token)
            q.execute()
        finally:
            print("ATLAS_RUNTIME_JOB_TERMINAL=" + str({
                "job_id": job_id,
                "state": "failed",
                "error": str(exc)[:500],
            }), flush=True)
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except _atlas_job_asyncio.CancelledError:
                pass
        _ATLAS_JOB_RUNNING.discard(job_id)


def _atlas_job_schedule(job_id):
    _atlas_job_asyncio.create_task(_atlas_job_execute(str(job_id)))


@app.post("/atlas/run-source/jobs", status_code=202)
async def atlas_run_source_job_submit(
    req: AtlasManifestJobRequest,
    x_atlas_token: str | None = _AtlasJobHeader(default=None),
):
    _atlas_job_require_token(x_atlas_token)
    _atlas_job_validate_request(req)

    existing = _atlas_job_by_key(req.idempotency_key)
    if existing:
        if existing.get("source_id") != req.source_id or int(existing.get("manifest_version") or 0) != int(req.manifest_version or 0):
            raise _AtlasJobHTTPException(status_code=409, detail="idempotency_key_identity_conflict")
        if existing.get("state") in {"queued", "running"}:
            _atlas_job_schedule(existing["job_id"])
        return _AtlasJobJSONResponse(
            status_code=202 if existing.get("state") in {"queued", "running"} else 200,
            content={**_atlas_job_public(existing), "replayed": True, "status_url": f"/atlas/run-source/jobs/{existing['job_id']}"},
        )

    now = _atlas_job_now_iso()
    request_data = req.model_dump(mode="json")
    request_data.pop("idempotency_key", None)
    insert = {
        "idempotency_key": req.idempotency_key,
        "operation": "run_source",
        "source_id": req.source_id,
        "manifest_version": req.manifest_version,
        "state": "queued",
        "request": request_data,
        "attempt_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    try:
        rows = supabase.table(_ATLAS_JOB_TABLE).insert(insert).execute().data or []
        row = dict(rows[0]) if rows else _atlas_job_by_key(req.idempotency_key)
    except Exception:
        row = _atlas_job_by_key(req.idempotency_key)
        if not row:
            raise
    if not row:
        raise _AtlasJobHTTPException(status_code=503, detail="runtime_job_persistence_failed")

    _atlas_job_schedule(row["job_id"])
    return _AtlasJobJSONResponse(
        status_code=202,
        content={**_atlas_job_public(row), "replayed": False, "status_url": f"/atlas/run-source/jobs/{row['job_id']}"},
    )


@app.get("/atlas/run-source/jobs/{job_id}")
async def atlas_run_source_job_status(
    job_id: str,
    x_atlas_token: str | None = _AtlasJobHeader(default=None),
):
    _atlas_job_require_token(x_atlas_token)
    try:
        _atlas_job_uuid.UUID(str(job_id))
    except Exception:
        raise _AtlasJobHTTPException(status_code=422, detail="invalid_job_id")
    row = _atlas_job_by_id(job_id)
    if not row:
        raise _AtlasJobHTTPException(status_code=404, detail="runtime_job_not_found")
    return _atlas_job_public(row)


@app.on_event("startup")
async def _atlas_runtime_job_recover_startup():
    if not supabase:
        print("ATLAS_ASYNC_RUN_SOURCE_CONTRACT=BLOCKED_SUPABASE", flush=True)
        return
    now = _atlas_job_now()
    queued = (
        supabase.table(_ATLAS_JOB_TABLE)
        .select("job_id")
        .eq("state", "queued")
        .limit(100)
        .execute().data or []
    )
    for row in queued:
        if row.get("job_id"):
            _atlas_job_schedule(row["job_id"])

    running = (
        supabase.table(_ATLAS_JOB_TABLE)
        .select("job_id,heartbeat_at,updated_at")
        .eq("state", "running")
        .limit(100)
        .execute().data or []
    )
    recovered = 0
    for row in running:
        last = _atlas_job_parse_dt(row.get("heartbeat_at") or row.get("updated_at"))
        if last is None or (now - last).total_seconds() >= _ATLAS_JOB_STALE_SECONDS:
            reset_at = _atlas_job_now_iso()
            supabase.table(_ATLAS_JOB_TABLE).update({
                "state": "queued",
                "claim_token": None,
                "heartbeat_at": None,
                "updated_at": reset_at,
                "error": "recovered_stale_running_job",
            }).eq("job_id", str(row.get("job_id"))).eq("state", "running").execute()
            _atlas_job_schedule(row.get("job_id"))
            recovered += 1

    print("ATLAS_ASYNC_RUN_SOURCE_CONTRACT=" + str({
        "version": 27,
        "submit": "/atlas/run-source/jobs",
        "status": "/atlas/run-source/jobs/{job_id}",
        "durable_table": _ATLAS_JOB_TABLE,
        "queued_recovered": len(queued),
        "stale_running_recovered": recovered,
    }), flush=True)
'''

p.write_text(s, encoding='utf-8')
print('Installed Atlas async run-source jobs v27')
