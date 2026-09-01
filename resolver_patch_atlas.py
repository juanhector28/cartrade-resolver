from pathlib import Path

# Keep Atlas shadow rows physically in the shared inventory table but outside
# production Carly paths. is_addressable is a generated Supabase column, so it
# must never be written directly.
rp = Path('/app/app/atlas_manifest_runner.py')
rs = rp.read_text(encoding='utf-8')
rs = rs.replace(
    '"status": "staging",\n            "is_addressable": False,',
    '"status": "atlas_shadow",'
)
rs = rs.replace(
    '"status": "atlas_shadow",\n            "is_addressable": False,',
    '"status": "atlas_shadow",'
)

# P0-0: shadow writes must never mutate a pre-existing production row. The
# shared table still has URL uniqueness, so a shadow run first inspects any
# existing owner. It may refresh only its own atlas_shadow row. Production rows
# and shadow rows owned by another source are immutable from this path.
_shadow_saved_anchor = '''        saved = 0\n        save_errors: list[str] = []\n'''
if _shadow_saved_anchor not in rs:
    raise RuntimeError('P0-0 saved-counter anchor missing')
rs = rs.replace(
    _shadow_saved_anchor,
    '''        saved = 0\n        protected_shadow_collisions = 0\n        protected_shadow_collision_urls: list[str] = []\n        save_errors: list[str] = []\n''',
    1,
)

_shadow_upsert_anchor = '''                    record = self._db_record(source_id, country, domain, manifest_version, item)\n                    self.supabase.table("scraped_listings").upsert(record, on_conflict="url").execute()\n                    saved += 1\n'''
if _shadow_upsert_anchor not in rs:
    raise RuntimeError('P0-0 shadow upsert anchor missing')
rs = rs.replace(
    _shadow_upsert_anchor,
    '''                    record = self._db_record(source_id, country, domain, manifest_version, item)\n                    existing = (\n                        self.supabase.table("scraped_listings")\n                        .select("status,raw_payload")\n                        .eq("url", record.get("url"))\n                        .limit(1)\n                        .execute().data or []\n                    )\n                    if existing:\n                        current = existing[0] or {}\n                        atlas_meta = ((current.get("raw_payload") or {}).get("atlas") or {})\n                        same_shadow_owner = bool(\n                            current.get("status") == "atlas_shadow"\n                            and atlas_meta.get("source_id") == source_id\n                        )\n                        if not same_shadow_owner:\n                            protected_shadow_collisions += 1\n                            if len(protected_shadow_collision_urls) < 10:\n                                protected_shadow_collision_urls.append(str(record.get("url") or ""))\n                            continue\n                    self.supabase.table("scraped_listings").upsert(record, on_conflict="url").execute()\n                    saved += 1\n''',
    1,
)

_shadow_return_anchor = '''            "saved_shadow": saved,\n            "required_success_pct": required_success_pct,\n'''
if _shadow_return_anchor not in rs:
    raise RuntimeError('P0-0 runner response anchor missing')
rs = rs.replace(
    _shadow_return_anchor,
    '''            "saved_shadow": saved,\n            "protected_shadow_collisions": protected_shadow_collisions,\n            "protected_shadow_collision_urls": protected_shadow_collision_urls,\n            "required_success_pct": required_success_pct,\n''',
    1,
)

# Runtime extraction success is not the same as activation quality. Attach a
# conservative semantic gate to every runner response so Atlas can keep a
# technically healthy source in shadow until its data is publication-safe.
semantic_marker = '# ATLAS_SEMANTIC_GATE_V1'
if semantic_marker not in rs:
    rs += r'''

# ATLAS_SEMANTIC_GATE_V1
_AtlasManifestRunner_run_without_semantic_gate = AtlasManifestRunner.run


def _atlas_scalar_text(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("name", "value", "title"):
            if value.get(key) is not None:
                return _atlas_scalar_text(value.get(key))
        return ""
    if isinstance(value, list):
        return " ".join(_atlas_scalar_text(v) for v in value)
    return str(value).strip()


def _atlas_activation_quality(sample):
    sample = list(sample or [])[:5]
    n = len(sample)
    if n < 3:
        return {
            "eligible": False,
            "sample_size": n,
            "score": 0.0,
            "issues": ["semantic_sample_too_small"],
        }

    nested_core = 0
    navigation_pollution = 0
    non_car = 0
    normalizable_price = 0
    plausible_year = 0
    photo_present = 0

    nav_values = {
        "inicio", "home", "buscar", "search", "menu", "menú", "vehiculos",
        "vehículos", "autos", "carros", "principal"
    }
    non_car_hints = (
        " motocic", "moto ", "/moto-", " atv", "atv ", "cuatri", "scooter",
        "quadric", "motocross"
    )

    for item in sample:
        for field in ("title", "make", "model"):
            if isinstance(item.get(field), (dict, list)):
                nested_core += 1

        for field in ("fuel_type", "transmission"):
            val = _atlas_scalar_text(item.get(field)).lower()
            if val in nav_values:
                navigation_pollution += 1

        # Ignore the generic Encuentra24 category slug "autos-motos" before
        # looking for motorcycle/ATV evidence in the listing itself.
        evidence = " ".join(
            _atlas_scalar_text(item.get(k)) for k in ("url", "title", "make", "model")
        ).lower().replace("autos-motos", "")
        if any(h in evidence for h in non_car_hints):
            non_car += 1

        if _money_usd(item.get("price_usd"), item.get("currency")) is not None:
            normalizable_price += 1

        try:
            year = int(item.get("year"))
            if 1950 <= year <= datetime.now(timezone.utc).year + 2:
                plausible_year += 1
        except Exception:
            pass

        photos = item.get("photos") or []
        if isinstance(photos, str):
            photos = [photos]
        if any(isinstance(p, str) and p.startswith("http") for p in photos):
            photo_present += 1

    issues = []
    if nested_core:
        issues.append("nested_core_fields")
    if navigation_pollution:
        issues.append("navigation_text_in_vehicle_fields")
    if non_car / n > 0.20:
        issues.append("non_car_inventory_detected")
    if normalizable_price / n < 0.80:
        issues.append("price_currency_not_normalizable")
    if plausible_year / n < 0.80:
        issues.append("year_quality_low")
    if photo_present / n < 0.80:
        issues.append("photo_coverage_low")

    checks = 6
    failures = len(issues)
    score = round(max(0.0, (checks - failures) / checks), 4)
    return {
        "eligible": not issues,
        "sample_size": n,
        "score": score,
        "issues": issues,
        "nested_core_fields": nested_core,
        "navigation_pollution": navigation_pollution,
        "non_car_ratio": round(non_car / n, 4),
        "normalizable_price_pct": round(normalizable_price / n * 100, 2),
        "plausible_year_pct": round(plausible_year / n * 100, 2),
        "photo_coverage_pct": round(photo_present / n * 100, 2),
    }


async def _atlas_run_with_semantic_gate(self, *args, **kwargs):
    result = await _AtlasManifestRunner_run_without_semantic_gate(self, *args, **kwargs)
    result["activation_quality"] = _atlas_activation_quality(result.get("sample") or [])
    return result


AtlasManifestRunner.run = _atlas_run_with_semantic_gate
'''

rp.write_text(rs, encoding='utf-8')

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')

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
        "runner": "atlas-manifest-v1.2",
        "bridge_token_configured": bool(os.environ.get("ATLAS_BRIDGE_TOKEN") or os.environ.get("CRON_TOKEN")),
        "supabase_connected": supabase is not None,
        "supported_modes": ["shadow"],
        "shadow_status": "atlas_shadow",
        "shadow_addressable": False,
        "generated_columns_safe": True,
        "semantic_activation_gate": True,
        "shadow_collision_protection": True,
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
else:
    # Existing block from earlier Atlas bridge versions: update only metadata.
    s = s.replace('"runner": "atlas-manifest-v1.1"', '"runner": "atlas-manifest-v1.2"')
    s = s.replace('"runner": "atlas-manifest-v1"', '"runner": "atlas-manifest-v1.2"')
    if '"semantic_activation_gate": True' not in s:
        s = s.replace(
            '"generated_columns_safe": True,',
            '"generated_columns_safe": True,\n        "semantic_activation_gate": True,'
        )
    if '"shadow_collision_protection": True' not in s:
        s = s.replace(
            '"semantic_activation_gate": True,',
            '"semantic_activation_gate": True,\n        "shadow_collision_protection": True,'
        )

# Resolver metadata bump only. Do not rewrite unrelated business logic.
for old in ('1.5.0', '1.6.0'):
    s = s.replace(f'version="{old}"', 'version="1.7.0"')
    s = s.replace(f'"version": "{old}"', '"version": "1.7.0"')

p.write_text(s, encoding='utf-8')
print('Applied Atlas Manifest Runner bridge; resolver version=1.7.0; semantic gate=v1; P0-0 protected')
