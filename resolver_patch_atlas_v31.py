from pathlib import Path

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
marker = '# ATLAS_PERSIST_CAPABILITY_V31'
if marker in s:
    raise RuntimeError('v31 persist capability patch already applied')

# 1) Persistence is opt-in everywhere by default.
old = '    persist: bool = True\n'
if s.count(old) != 1:
    raise RuntimeError(f'v31 persist default anchor count={s.count(old)}')
s = s.replace(old, '    persist: bool = False\n', 1)

# 2) Synchronous /atlas/run-source requires a dedicated Publisher capability
# in addition to the ordinary Atlas bridge token when persist=True.
old = 'async def atlas_run_source(req: AtlasManifestRunRequest, x_atlas_token: str | None = _AtlasHeader(default=None)):\n    _require_atlas_bridge_token(x_atlas_token)\n    if req.mode != "shadow":\n'
new = '''async def atlas_run_source(\n    req: AtlasManifestRunRequest,\n    x_atlas_token: str | None = _AtlasHeader(default=None),\n    x_atlas_publisher_token: str | None = _AtlasHeader(default=None, alias="X-Atlas-Publisher-Token"),\n):\n    _require_atlas_bridge_token(x_atlas_token)\n    if req.persist:\n        import hmac as _atlas_persist_hmac\n        _atlas_persist_expected = os.environ.get("ATLAS_PUBLISH_TOKEN") or ""\n        if not _atlas_persist_expected:\n            raise HTTPException(status_code=503, detail="Atlas persist capability is not configured")\n        if not x_atlas_publisher_token or not _atlas_persist_hmac.compare_digest(\n            str(x_atlas_publisher_token), str(_atlas_persist_expected)\n        ):\n            raise HTTPException(status_code=401, detail="invalid atlas persist capability")\n    if req.mode != "shadow":\n'''
if old not in s:
    raise RuntimeError('v31 sync run-source anchor missing')
s = s.replace(old, new, 1)

# 3) Async submit requires the same capability. The token itself is never
# written to the runtime-jobs table; only a server-issued capability marker is.
old = '''async def atlas_run_source_job_submit(\n    req: AtlasManifestJobRequest,\n    x_atlas_token: str | None = _AtlasJobHeader(default=None),\n):\n    _atlas_job_require_token(x_atlas_token)\n    _atlas_job_validate_request(req)\n'''
new = '''async def atlas_run_source_job_submit(\n    req: AtlasManifestJobRequest,\n    x_atlas_token: str | None = _AtlasJobHeader(default=None),\n    x_atlas_publisher_token: str | None = _AtlasJobHeader(default=None, alias="X-Atlas-Publisher-Token"),\n):\n    _atlas_job_require_token(x_atlas_token)\n    if req.persist:\n        import hmac as _atlas_job_persist_hmac\n        _atlas_job_persist_expected = _atlas_job_os.getenv("ATLAS_PUBLISH_TOKEN") or ""\n        if not _atlas_job_persist_expected:\n            raise _AtlasJobHTTPException(status_code=503, detail="Atlas persist capability is not configured")\n        if not x_atlas_publisher_token or not _atlas_job_persist_hmac.compare_digest(\n            str(x_atlas_publisher_token), str(_atlas_job_persist_expected)\n        ):\n            raise _AtlasJobHTTPException(status_code=401, detail="invalid atlas persist capability")\n    _atlas_job_validate_request(req)\n'''
if old not in s:
    raise RuntimeError('v31 async submit anchor missing')
s = s.replace(old, new, 1)

old = '''    request_data = req.model_dump(mode="json")\n    request_data.pop("idempotency_key", None)\n    insert = {\n'''
new = '''    request_data = req.model_dump(mode="json")\n    request_data.pop("idempotency_key", None)\n    if req.persist:\n        request_data["_persist_capability"] = "publisher"\n    insert = {\n'''
if old not in s:
    raise RuntimeError('v31 async request persistence anchor missing')
s = s.replace(old, new, 1)

# 4) Executor rejects old/manually injected persist=True jobs that lack the
# server-issued marker, so authorization is durable across queue delay/restart.
old = '''        request_data = dict(claimed.get("request") or {})\n        req = AtlasManifestRunRequest(**request_data)\n        domain = _atlas_job_validate_request(req)\n'''
new = '''        request_data = dict(claimed.get("request") or {})\n        _persist_capability = request_data.pop("_persist_capability", None)\n        req = AtlasManifestRunRequest(**request_data)\n        if req.persist and _persist_capability != "publisher":\n            raise RuntimeError("persist_true_job_missing_publisher_capability")\n        domain = _atlas_job_validate_request(req)\n'''
if old not in s:
    raise RuntimeError('v31 async executor capability anchor missing')
s = s.replace(old, new, 1)

s += '''\n\n# ATLAS_PERSIST_CAPABILITY_V31\n# persist=False is the default. persist=True requires ATLAS_PUBLISH_TOKEN via\n# X-Atlas-Publisher-Token at submit time; async jobs carry only a server-issued\n# non-secret capability marker and fail closed if it is absent.\n'''
p.write_text(s, encoding='utf-8')
print('Installed ATLAS_PERSIST_CAPABILITY_V31')
