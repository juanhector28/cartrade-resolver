"""Offline tests: challenge verification must be both genuine and rate limited."""
from __future__ import annotations

import json

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.link_first_turnstile import ACTION, VERIFY_URL, TurnstileBuyerVerifier


def build(success=True, hostname="bright-dragon-cd29a3.netlify.app",
          action=ACTION, allowed=True, secret="synthetic-server-secret"):
    received = []
    limited = []

    def handler(req: httpx.Request):
        received.append(req)
        assert str(req.url) == VERIFY_URL
        assert req.method == "POST"
        assert "synthetic-server-secret" in req.content.decode("utf-8")
        return httpx.Response(200, json={
            "success": success, "hostname": hostname, "action": action
        })

    def limiter(peer: str) -> bool:
        limited.append(peer)
        return allowed

    verifier = TurnstileBuyerVerifier(
        secret_key=secret, expected_hostname="bright-dragon-cd29a3.netlify.app",
        limiter=limiter, transport=httpx.MockTransport(handler),
    )
    app = FastAPI()

    @app.post("/verify")
    async def verify(request: Request):
        ok = await verifier(request)
        if not ok:
            raise HTTPException(429, "Challenge invalid")
        return {"ok": True}

    return TestClient(app), received, limited


def submit(client: TestClient, token: str = "synthetic-turnstile-token-long-enough"):
    return client.post("/verify", json={
        "turnstile_token": token,
        "listing_url": "https://www.facebook.com/marketplace/item/123456/",
        "buyer_contact": "THIS_MUST_NOT_BE_USED_FOR_SITEVERIFY",
    })


def test_valid_token_requires_matching_hostname_action_and_limiter():
    client, upstream, quotas = build()
    assert submit(client).status_code == 200
    assert len(upstream) == 1
    assert len(quotas) == 1
    raw = upstream[0].content.decode("utf-8")
    assert "THIS_MUST_NOT_BE_USED_FOR_SITEVERIFY" not in raw


def test_reject_wrong_hostname_even_if_cloudflare_says_success():
    client, _, _ = build(hostname="evil.example")
    assert submit(client).status_code == 429


def test_reject_wrong_action_even_if_challenge_valid():
    client, _, _ = build(action="some_other_form")
    assert submit(client).status_code == 429


def test_reject_unsuccessful_challenge():
    client, _, _ = build(success=False)
    assert submit(client).status_code == 429


def test_reject_missing_or_malformed_token_before_cloudflare():
    client, upstream, _ = build()
    assert client.post("/verify", json={"listing_url": "https://example.com"}).status_code == 429
    assert submit(client, "tiny").status_code == 429
    assert submit(client, "x" * 2049).status_code == 429
    assert len(upstream) == 0


def test_reject_without_quota_without_siteverify_call():
    client, upstream, _ = build(allowed=False)
    assert submit(client).status_code == 429
    assert len(upstream) == 0


def test_reject_missing_secret():
    client, upstream, _ = build(secret="")
    assert submit(client).status_code == 429
    assert len(upstream) == 0


def test_upstream_error_rejects_not_accepts():
    client, received, quotas = build()

    def broken(req):
        raise httpx.TimeoutException("simulated timeout")

    # The real endpoint never stores PII if Cloudflare's API times out.
    from app.link_first_turnstile import TurnstileBuyerVerifier
    verifier = TurnstileBuyerVerifier(
        secret_key="test-secret",
        expected_hostname="bright-dragon-cd29a3.netlify.app",
        limiter=lambda _peer: True,
        transport=httpx.MockTransport(broken),
    )
    app = FastAPI()

    @app.post("/verify")
    async def route(request: Request):
        return {"ok": await verifier(request)}

    result = TestClient(app).post("/verify", json={"turnstile_token": "synthetic-valid-length"})
    assert result.json() == {"ok": False}
