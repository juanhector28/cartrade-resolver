import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from app import social_intake as intake


@pytest.mark.parametrize("url", ["https://instagram.com/p/abc", "https://vm.tiktok.com/abc", "https://facebook.com/story.php?story_fbid=1&id=2"])
def test_recognizes_social_references(url):
    assert intake.social_platform(url)


@pytest.mark.parametrize("url", ["http://instagram.com/p/a", "https://instagram.com.evil.test/p/a", "https://user:pass@instagram.com/p/a", "https://instagram.com:443/p/a", "https://localhost/p/a"])
def test_rejects_unsafe_urls(url):
    assert intake.social_platform(url) is None


def test_capture_sends_only_to_atlas(monkeypatch):
    monkeypatch.setenv("ATLAS_SOCIAL_URL", "https://atlas.example")
    monkeypatch.setenv("ATLAS_SOCIAL_TOKEN", "test-token")
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "candidate-one"})
    client = httpx.AsyncClient
    monkeypatch.setattr(intake.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
    result = asyncio.run(intake.capture_reference("https://instagram.com/p/abc", "sv"))
    assert len(seen) == 1 and seen[0].url.host == "atlas.example"
    assert seen[0].headers["X-Atlas-Token"] == "test-token"
    assert result["candidate_saved"] and not result["saved"] and not result["live_verified"]


def test_unconfigured_bridge_does_not_claim_saved(monkeypatch):
    monkeypatch.delenv("ATLAS_SOCIAL_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(intake.capture_reference("https://instagram.com/p/abc", "GT"))
    assert exc.value.status_code == 503


def test_country_is_required():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(intake.capture_reference("https://instagram.com/p/abc", None))
    assert exc.value.status_code == 422
