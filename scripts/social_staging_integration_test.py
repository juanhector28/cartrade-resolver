import httpx
import pytest
from fastapi.testclient import TestClient
from app import paste_link_staging as staging
from app import social_intake
from atlas.social_discovery import SocialDiscoveryEngine


@pytest.mark.parametrize('platform,url,country', [
    ('facebook','https://facebook.com/marketplace/item/123','SV'),
    ('instagram','https://instagram.com/p/example','GT'),
    ('tiktok','https://www.tiktok.com/@dealer/video/123','SV'),
])
def test_staging_receipt_persists_only_candidate(tmp_path, monkeypatch, platform, url, country):
    engine = SocialDiscoveryEngine(str(tmp_path/'social.json'))
    monkeypatch.setenv('ATLAS_SOCIAL_URL','https://atlas.example')
    monkeypatch.setenv('ATLAS_SOCIAL_TOKEN','test-token')
    def handle(request):
        import json
        if request.url.host == 'www.tiktok.com':
            return httpx.Response(403)
        assert request.url.host == 'atlas.example'
        return httpx.Response(200,json=engine.ingest(json.loads(request.content)))
    original = httpx.AsyncClient
    monkeypatch.setattr(social_intake.httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(handle),**kw))
    staging._limits.clear()
    with TestClient(staging.app) as client:
        reply = client.post('/api/resolve',json={'url':url,'country':country})
    assert reply.status_code == 200
    data = reply.json()
    assert data['candidate_saved'] and not data['saved'] and not data['in_inventory']
    row = SocialDiscoveryEngine(str(tmp_path/'social.json')).list_candidates()[0]
    assert row['id'] == data['candidate_id'] and row['platform'] == platform
    assert row['status'] == 'awaiting_metadata' and not row['inventory_eligible']


def test_missing_connection_returns_error_without_receipt(monkeypatch):
    monkeypatch.delenv('ATLAS_SOCIAL_TOKEN',raising=False)
    staging._limits.clear()
    with TestClient(staging.app) as client:
        r = client.post('/api/resolve',json={'url':'https://instagram.com/p/example','country':'SV'})
    assert r.status_code == 503 and 'candidate_saved' not in r.json()


def test_receipt_ui_requires_confirmed_candidate():
    assert 'd.candidate_saved === true' in staging.STAGING_PAGE
    assert 'Recibimos el enlace. Nos encargamos del resto.' in staging.STAGING_PAGE
