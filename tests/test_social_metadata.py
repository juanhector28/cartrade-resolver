import asyncio
import httpx
from app import social_metadata as metadata


def test_official_endpoint_and_no_embed_html(monkeypatch):
    calls=[]
    def handle(request):
        calls.append(request)
        return httpx.Response(200,json={'type':'video','provider_name':'TikTok','title':'Toyota Corolla 2020 $12,500','thumbnail_url':'https://example.com/car.jpg','html':'<script>unsafe</script>'})
    original=httpx.AsyncClient
    monkeypatch.setattr(metadata.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    r=asyncio.run(metadata.recover_metadata('https://www.tiktok.com/@dealer/video/123','tiktok'))
    assert r['title'].startswith('Toyota') and 'html' not in r
    assert calls[0].url.host=='www.tiktok.com' and calls[0].url.path=='/oembed'


def test_short_link_and_other_platform_are_explicit():
    assert asyncio.run(metadata.recover_metadata('https://vm.tiktok.com/abc','tiktok'))['metadata_status']=='canonical_video_link_required'
    assert asyncio.run(metadata.recover_metadata('https://instagram.com/p/a','instagram'))['metadata_status']=='provider_not_connected'


def test_unavailable_provider_is_not_fatal(monkeypatch):
    original=httpx.AsyncClient
    monkeypatch.setattr(metadata.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(403)),**kw))
    assert asyncio.run(metadata.recover_metadata('https://www.tiktok.com/@dealer/video/123','tiktok'))=={'metadata_status':'unavailable'}
