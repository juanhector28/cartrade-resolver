"""Draft anti-abuse verifier for link-first buyer requests.

Never mounted on a public service by itself. Turnstile Siteverify must succeed
AND a distributed rate-limit callback must allow the request. Both checks are
mandatory, and any missing configuration or transport issue fails closed.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import Request

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
ACTION = "cartrade_link_first"


class TurnstileBuyerVerifier:
    """Callable for app.state.link_first_abuse_verifier in a future controlled app.

    Pass a shared datastore-backed limiter: callable(peer_ip)->bool or awaitable.
    Never derive the peer address from client-supplied Forwarded/XFF headers.
    Do not deploy a single-process memory limiter as the production quota.
    """

    def __init__(
        self,
        *,
        secret_key: str,
        expected_hostname: str,
        limiter: Callable[[str], Any] | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._secret = secret_key
        self._hostname = expected_hostname
        self._limiter = limiter
        self._transport = transport

    async def __call__(self, request: Request) -> bool:
        if not self._secret or not self._hostname or self._limiter is None:
            return False

        try:
            body = await request.json()
            token = body.get("turnstile_token") if isinstance(body, dict) else None
            if not isinstance(token, str) or not 10 <= len(token) <= 2048:
                return False
            peer = request.client.host if request.client else None
            if not peer:
                return False

            allowed = self._limiter(peer)
            if inspect.isawaitable(allowed):
                allowed = await allowed
            if allowed is not True:
                return False

            async with httpx.AsyncClient(
                timeout=6.0, follow_redirects=False, transport=self._transport
            ) as client:
                response = await client.post(
                    VERIFY_URL,
                    data={"secret": self._secret, "response": token},
                )
                response.raise_for_status()
                result = response.json()
            return (
                isinstance(result, dict)
                and result.get("success") is True
                and result.get("hostname") == self._hostname
                and result.get("action") == ACTION
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return False
        except Exception:
            # Do not log tokens, phone numbers or other request content.
            return False
