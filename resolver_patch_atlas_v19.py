from pathlib import Path


p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
marker = '# ATLAS_CARLY_PROVENANCE_V19'
if marker not in s:
    request_anchor = '''class CarlySearchRequest(BaseModel):\n    q: str = ""\n    country: Optional[str] = None\n    limit: int = 3\n    addressable_only: bool = True\n'''
    request_new = '''class CarlySearchRequest(BaseModel):\n    q: str = ""\n    country: Optional[str] = None\n    limit: int = 3\n    addressable_only: bool = True\n    source_id: Optional[str] = None\n    manifest_version: Optional[int] = None\n'''
    if request_anchor not in s:
        raise RuntimeError('v19 CarlySearchRequest anchor missing')
    s = s.replace(request_anchor, request_new, 1)

    cols_anchor = '''    "visible_damage_risk,damage_signals,vision_checked_at,listing_state"\n)'''
    cols_new = '''    "visible_damage_risk,damage_signals,vision_checked_at,listing_state,source,raw_payload"\n)'''
    if cols_anchor not in s:
        raise RuntimeError('v19 CARLY_COLS anchor missing')
    s = s.replace(cols_anchor, cols_new, 1)

    filter_anchor = '''    if body.country:\n        q = q.eq("country", body.country)\n    if it.body_types:\n'''
    filter_new = '''    if body.country:\n        q = q.eq("country", body.country)\n    if body.source_id:\n        atlas_filter = {"atlas": {"source_id": body.source_id}}\n        if body.manifest_version is not None:\n            atlas_filter["atlas"]["manifest_version"] = int(body.manifest_version)\n        q = q.contains("raw_payload", atlas_filter)\n    if it.body_types:\n'''
    if filter_anchor not in s:
        raise RuntimeError('v19 Carly provenance filter anchor missing')
    s = s.replace(filter_anchor, filter_new, 1)

    result_anchor = '''    for i, item in enumerate(ranked):\n        car = item["car"]\n        char = _character_for(car)'''
    result_new = '''    for i, item in enumerate(ranked):\n        car = item["car"]\n        raw_payload = car.get("raw_payload") if isinstance(car, dict) else None\n        atlas_meta = (raw_payload or {}).get("atlas") if isinstance(raw_payload, dict) else None\n        atlas_meta = atlas_meta if isinstance(atlas_meta, dict) else {}\n        provenance_source_id = atlas_meta.get("source_id") or car.get("source")\n        provenance_manifest_version = atlas_meta.get("manifest_version")\n        char = _character_for(car)'''
    if result_anchor not in s:
        raise RuntimeError('v19 Carly result provenance anchor missing')
    s = s.replace(result_anchor, result_new, 1)

    append_anchor = '''            "reserved": item["state"] == "reservado",\n            "why": why,\n            "character": character_out,                  # NUEVO: carácter del modelo\n'''
    append_new = '''            "reserved": item["state"] == "reservado",\n            "source_id": provenance_source_id,\n            "manifest_version": provenance_manifest_version,\n            "why": why,\n            "character": character_out,                  # NUEVO: carácter del modelo\n'''
    if append_anchor not in s:
        raise RuntimeError('v19 Carly response anchor missing')
    s = s.replace(append_anchor, append_new, 1)

    s += '\n# ATLAS_CARLY_PROVENANCE_V19\n'

for old in ('1.12.0', '1.13.0'):
    s = s.replace(f'version="{old}"', 'version="1.14.0"')
    s = s.replace(f'"version": "{old}"', '"version": "1.14.0"')

p.write_text(s, encoding='utf-8')
print('Installed production Carly Atlas provenance contract; resolver version=1.14.0')
