from pathlib import Path

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
marker = '# ATLAS_FACTORY_HARNESS_CONTRACT_V1'
if marker not in s:
    s = s.replace(
        '"visible_damage_risk,damage_signals,vision_checked_at,listing_state"\n)',
        '"visible_damage_risk,damage_signals,vision_checked_at,listing_state,source,raw_payload"\n)',
        1,
    )
    s = s.replace(
        '    m_num = re.search(r"\\$?\\s*(\\d{4,6})", t)\n',
        '    m_year = re.search(r"\\b(19\\d{2}|20\\d{2})\\b", t)\n'
        '    m_num = re.search(r"\\$?\\s*(\\d{4,6})", t)\n'
        '    if m_num and m_year and m_num.group(1) == m_year.group(1):\n'
        '        m_num = None\n',
        1,
    )
    s = s.replace(
        '        car = item["car"]\n        char = _character_for(car)',
        '        car = item["car"]\n        provenance = _atlas_carly_provenance(car)\n        char = _character_for(car)',
        1,
    )
    anchor = '''            "tag": TAGS[i] if i < len(TAGS) else "Opción",\n'''
    replacement = '''            "source_id": provenance.get("source_id"),\n            "manifest_version": provenance.get("manifest_version"),\n            "tag": TAGS[i] if i < len(TAGS) else "Opción",\n'''
    if anchor not in s:
        raise RuntimeError('Factory harness Carly result anchor missing')
    s = s.replace(anchor, replacement, 1)
    insert = r'''

# ATLAS_FACTORY_HARNESS_CONTRACT_V1
from .atlas_provenance import carly_provenance as _atlas_carly_provenance
from fastapi import Header as _AtlasHarnessHeader


class _AtlasFixtureReachabilityRequest(BaseModel):
    url: str


@app.post('/atlas/test/fixture-reachability')
async def atlas_test_fixture_reachability(req: _AtlasFixtureReachabilityRequest, x_atlas_token: str | None = _AtlasHarnessHeader(default=None)):
    if os.getenv('ATLAS_TEST_ENV') != '1':
        raise HTTPException(status_code=404, detail='not found')
    expected = os.getenv('ATLAS_BRIDGE_TOKEN') or os.getenv('CRON_TOKEN') or ''
    if not expected or x_atlas_token != expected:
        raise HTTPException(status_code=401, detail='invalid atlas bridge token')
    fixture_base = (os.getenv('ATLAS_FIXTURE_BASE_URL') or '').rstrip('/')
    if not fixture_base or not req.url.startswith(fixture_base + '/'):
        raise HTTPException(status_code=422, detail='fixture URL outside ATLAS_FIXTURE_BASE_URL')
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(req.url)
        return {'reachable': response.status_code == 200, 'status_code': response.status_code, 'url': str(response.url)}
    except Exception as exc:
        return {'reachable': False, 'error': str(exc)[:300], 'url': req.url}
'''
    s += insert
p.write_text(s, encoding='utf-8')
print('Applied branch-only Atlas Factory harness Resolver contract')
