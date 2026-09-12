from pathlib import Path

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
marker = '# ATLAS_PUBLISH_ASYNC_V28'

if marker not in s:
    # v27 owns run_source jobs. Keep its recovery/executor scoped so publish jobs
    # in the same durable ledger can never be claimed by the wrong worker.
    old = '''        row = _atlas_job_by_id(job_id)\n        if not row or row.get("state") != "queued":\n            return\n'''
    new = '''        row = _atlas_job_by_id(job_id)\n        if not row or row.get("state") != "queued" or row.get("operation") != "run_source":\n            return\n'''
    if old not in s:
        raise RuntimeError('v28 run-source executor scope anchor missing')
    s = s.replace(old, new, 1)

    old = '''        .select("job_id")\n        .eq("state", "queued")\n        .limit(100)\n'''
    new = '''        .select("job_id")\n        .eq("operation", "run_source")\n        .eq("state", "queued")\n        .limit(100)\n'''
    if old not in s:
        raise RuntimeError('v28 run-source queued recovery anchor missing')
    s = s.replace(old, new, 1)

    old = '''        .select("job_id,heartbeat_at,updated_at")\n        .eq("state", "running")\n        .limit(100)\n'''
    new = '''        .select("job_id,heartbeat_at,updated_at")\n        .eq("operation", "run_source")\n        .eq("state", "running")\n        .limit(100)\n'''
    if old not in s:
        raise RuntimeError('v28 run-source running recovery anchor missing')
    s = s.replace(old, new, 1)

    s += r'''

# ATLAS_PUBLISH_ASYNC_V28
from app.atlas_publish_api import (
    AtlasPublishRequest as _AtlasPublishJobBaseRequest,
    publish_source as _atlas_publish_job_sync,
)

_ATLAS_PUBLISH_JOB_RUNNING = set()


class AtlasPublishJobRequest(_AtlasPublishJobBaseRequest):
    job_idempotency_key: str = _AtlasJobField(min_length=8, max_length=500)


async def _atlas_publish_job_execute(job_id):
    job_id = str(job_id)
    if job_id in _ATLAS_PUBLISH_JOB_RUNNING:
        return
    _ATLAS_PUBLISH_JOB_RUNNING.add(job_id)
    heartbeat_task = None
    claim_token = None
    try:
        row = _atlas_job_by_id(job_id)
        if not row or row.get("state") != "queued" or row.get("operation") != "publish_source":
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
        }).eq("job_id", job_id).eq("operation", "publish_source").eq("state", "queued").is_("claim_token", "null").execute()

        claimed = _atlas_job_by_id(job_id)
        if not claimed or claimed.get("state") != "running" or claimed.get("claim_token") != claim_token:
            return

        request_data = dict(claimed.get("request") or {})
        req = _AtlasPublishJobBaseRequest(**request_data)
        heartbeat_task = _atlas_job_asyncio.create_task(_atlas_job_heartbeat(job_id, claim_token))

        result = await _atlas_job_asyncio.to_thread(_atlas_publish_job_sync, supabase, req)
        done = _atlas_job_now_iso()
        supabase.table(_ATLAS_JOB_TABLE).update({
            "state": "succeeded",
            "result": result,
            "error": None,
            "heartbeat_at": done,
            "completed_at": done,
            "updated_at": done,
        }).eq("job_id", job_id).eq("operation", "publish_source").eq("claim_token", claim_token).eq("state", "running").execute()
        print("ATLAS_PUBLISH_JOB_TERMINAL=" + str({
            "job_id": job_id,
            "source_id": req.source_id,
            "manifest_version": req.manifest_version,
            "dry_run": req.dry_run,
            "result": (result or {}).get("result"),
            "state": "succeeded",
        }), flush=True)
    except Exception as exc:
        try:
            failed = _atlas_job_now_iso()
            q = supabase.table(_ATLAS_JOB_TABLE).update({
                "state": "failed",
                "error": str(exc)[:4000],
                "heartbeat_at": failed,
                "completed_at": failed,
                "updated_at": failed,
            }).eq("job_id", job_id).eq("operation", "publish_source").eq("state", "running")
            if claim_token:
                q = q.eq("claim_token", claim_token)
            q.execute()
        finally:
            print("ATLAS_PUBLISH_JOB_TERMINAL=" + str({
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
        _ATLAS_PUBLISH_JOB_RUNNING.discard(job_id)


def _atlas_publish_job_schedule(job_id):
    _atlas_job_asyncio.create_task(_atlas_publish_job_execute(str(job_id)))


@app.post("/atlas/publish-source/jobs", status_code=202)
async def atlas_publish_source_job_submit(
    req: AtlasPublishJobRequest,
    x_atlas_token: str | None = _AtlasJobHeader(default=None),
):
    _atlas_job_require_token(x_atlas_token)
    if not supabase:
        raise _AtlasJobHTTPException(status_code=503, detail="Supabase is not connected")

    natural_key = f"publish:{req.source_id.strip()}:{int(req.manifest_version)}"
    if req.idempotency_key != natural_key:
        raise _AtlasJobHTTPException(status_code=422, detail="publish_idempotency_key_must_match_natural_key")
    if not req.dry_run and not req.expected_snapshot_hash:
        raise _AtlasJobHTTPException(status_code=422, detail="expected_snapshot_hash_required_v2")

    existing = _atlas_job_by_key(req.job_idempotency_key)
    if existing:
        if (
            existing.get("operation") != "publish_source"
            or existing.get("source_id") != req.source_id
            or int(existing.get("manifest_version") or 0) != int(req.manifest_version or 0)
        ):
            raise _AtlasJobHTTPException(status_code=409, detail="job_idempotency_key_identity_conflict")
        if existing.get("state") in {"queued", "running"}:
            _atlas_publish_job_schedule(existing["job_id"])
        return _AtlasJobJSONResponse(
            status_code=202 if existing.get("state") in {"queued", "running"} else 200,
            content={**_atlas_job_public(existing), "replayed": True, "status_url": f"/atlas/publish-source/jobs/{existing['job_id']}"},
        )

    now = _atlas_job_now_iso()
    request_data = req.model_dump(mode="json")
    request_data.pop("job_idempotency_key", None)
    insert = {
        "idempotency_key": req.job_idempotency_key,
        "operation": "publish_source",
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
        row = dict(rows[0]) if rows else _atlas_job_by_key(req.job_idempotency_key)
    except Exception:
        row = _atlas_job_by_key(req.job_idempotency_key)
        if not row:
            raise
    if not row:
        raise _AtlasJobHTTPException(status_code=503, detail="publish_job_persistence_failed")

    _atlas_publish_job_schedule(row["job_id"])
    return _AtlasJobJSONResponse(
        status_code=202,
        content={**_atlas_job_public(row), "replayed": False, "status_url": f"/atlas/publish-source/jobs/{row['job_id']}"},
    )


@app.get("/atlas/publish-source/jobs/{job_id}")
async def atlas_publish_source_job_status(
    job_id: str,
    x_atlas_token: str | None = _AtlasJobHeader(default=None),
):
    _atlas_job_require_token(x_atlas_token)
    try:
        _atlas_job_uuid.UUID(str(job_id))
    except Exception:
        raise _AtlasJobHTTPException(status_code=422, detail="invalid_job_id")
    row = _atlas_job_by_id(job_id)
    if not row or row.get("operation") != "publish_source":
        raise _AtlasJobHTTPException(status_code=404, detail="publish_job_not_found")
    return _atlas_job_public(row)


@app.on_event("startup")
async def _atlas_publish_job_recover_startup():
    if not supabase:
        print("ATLAS_ASYNC_PUBLISH_CONTRACT=BLOCKED_SUPABASE", flush=True)
        return
    now = _atlas_job_now()
    queued = (
        supabase.table(_ATLAS_JOB_TABLE)
        .select("job_id")
        .eq("operation", "publish_source")
        .eq("state", "queued")
        .limit(100)
        .execute().data or []
    )
    for row in queued:
        if row.get("job_id"):
            _atlas_publish_job_schedule(row["job_id"])

    running = (
        supabase.table(_ATLAS_JOB_TABLE)
        .select("job_id,heartbeat_at,updated_at")
        .eq("operation", "publish_source")
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
                "error": "recovered_stale_running_publish_job",
            }).eq("job_id", str(row.get("job_id"))).eq("operation", "publish_source").eq("state", "running").execute()
            _atlas_publish_job_schedule(row.get("job_id"))
            recovered += 1

    print("ATLAS_ASYNC_PUBLISH_CONTRACT=" + str({
        "version": 28,
        "submit": "/atlas/publish-source/jobs",
        "status": "/atlas/publish-source/jobs/{job_id}",
        "durable_table": _ATLAS_JOB_TABLE,
        "queued_recovered": len(queued),
        "stale_running_recovered": recovered,
    }), flush=True)
'''

p.write_text(s, encoding='utf-8')
print('Installed Atlas durable async publish jobs v28')
