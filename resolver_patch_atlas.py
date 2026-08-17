from pathlib import Path

# Keep Atlas shadow rows physically in the shared inventory table but outside
# production Carly paths. `is_addressable` is a GENERATED Supabase column, so
# the runner must never try to write it directly.
rp = Path('/app/app/atlas_manifest_runner.py')
rs = rp.read_text(encoding='utf-8')
rs = rs.replace(
    '"status": "staging",\n            "is_addressable": False,',
    '"status": "atlas_shadow",',
)
rp.write_text(rs, encoding='utf-8')

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')

# Defense in depth: deterministic Carly search must require the production
# staging status as well as the generated is_addressable flag. This guarantees
# Atlas shadow rows cannot surface even if the generated-column expression does
# not itself know about the Atlas lifecycle.
s = s.replace(
    'if body.addressable_only:\n        q = q.eq("is_addressable", True)',
    'if body.addressable_only:\n        q = q.eq("status", "staging").eq("is_addressable", True)',
)

marker = '# ATLAS_MANIFEST_RUNNER_V1'
if marker not in s:
    block = r'''

# ATLAS_MANIFEST_RUNNER_V1
from fastapi import Header as _AtlasHeader
from .atlas_manifest_runner import AtlasManifestRunner as _AtlasManifestRunner

_atlas_manifest_runner = _AtlasManifestRunner(supabase=supabase)

class AtlasManifestRunRequest(BaseModel):
    source_id: str
    country: str
    domain: str | None = None
    manifest_version: int | None = None
    manifest: dict
    mode: str = "shadow"
    limit: int = 20
    scan_limit: int = 80
    persist: bool = True


def _require_atlas_bridge_token(x_atlas_token: str | None):
    expected = os.environ.get("ATLAS_BRIDGE_TOKEN") or os.environ.get("CRON_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="ATLAS_BRIDGE_TOKEN is not configured")
    if not x_atlas_token or x_atlas_token != expected:
        raise HTTPException(status_code=401, detail="invalid atlas bridge token")


@app.get("/atlas/runner/status")
def atlas_runner_status():
    return {
        "ok": True,
        "runner": "atlas-manifest-v1.1",
        "bridge_token_configured": bool(os.environ.get("ATLAS_BRIDGE_TOKEN") or os.environ.get("CRON_TOKEN")),
        "supabase_connected": supabase is not None,
        "supported_modes": ["shadow"],
        "shadow_status": "atlas_shadow",
        "shadow_addressable": False,
        "generated_columns_safe": True,
    }


@app.post("/atlas/run-source")
async def atlas_run_source(req: AtlasManifestRunRequest, x_atlas_token: str | None = _AtlasHeader(default=None)):
    _require_atlas_bridge_token(x_atlas_token)
    if req.mode != "shadow":
        raise HTTPException(status_code=422, detail="v1 runner only permits mode=shadow")
    if len((req.country or "").strip()) != 2:
        raise HTTPException(status_code=422, detail="country must be a two-letter code")
    if not req.source_id.startswith(req.country.lower() + "-"):
        raise HTTPException(status_code=422, detail="source_id/country mismatch")
    base_url = str((req.manifest or {}).get("base_url") or "")
    domain = (req.domain or "").strip().lower()
    if not domain and base_url:
        from urllib.parse import urlparse as _atlas_urlparse
        domain = _atlas_urlparse(base_url).netloc.lower().removeprefix("www.")
    if not domain:
        raise HTTPException(status_code=422, detail="domain is required")
    if req.persist and not supabase:
        raise HTTPException(status_code=503, detail="Supabase is not connected")

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
    return result
'''
    s += block

# Resolver metadata bump only. Do not rewrite unrelated business logic.
s = s.replace('version="1.5.0"', 'version="1.6.1"')
s = s.replace('"version": "1.5.0"', '"version": "1.6.1"')

p.write_text(s, encoding='utf-8')
print('Applied Atlas Manifest Runner bridge; resolver version=1.6.1')
