"""Carly v8 composition root.

The CarTrade frontend appends a ``[CONTEXTO ACTIVO DE CARTRADE: ...]`` block to
the latest user message before every /carly/chat request. That metadata is useful
to the richer guarded path, but the deterministic fastpath previously saw the
raw suffix. A reply that was visibly just ``500`` therefore no longer matched the
standalone-money parser and Carly asked the monthly-budget question again.

v8 makes the visible buyer text authoritative for the zero-token parser while
leaving the full frontend context available to the guarded/LLM path.
"""
from __future__ import annotations

import re
from typing import Any

from . import carly_fastpath as fastpath
from . import main_v7 as v7

app = v7.app
commercial = v7.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v8-context-clean"

_CONTEXT_BLOCK_RE = re.compile(
    r"\s*\[CONTEXTO ACTIVO DE CARTRADE:.*$",
    re.I | re.S,
)


def _strip_frontend_context(text: Any) -> str:
    return _CONTEXT_BLOCK_RE.sub("", str(text or "")).strip()


def _install_visible_text_parser() -> None:
    # carly_fastpath owns user_text(), monthly parsing and intake_state(). All of
    # them resolve the module-level _content function at call time, so this one
    # patch fixes the whole zero-token path without changing the LLM context.
    if not getattr(fastpath._content, "_carly_visible_text", False):
        prior_fast_content = fastpath._content

        def visible_fast_content(message: Any) -> str:
            return _strip_frontend_context(prior_fast_content(message))

        visible_fast_content._carly_visible_text = True
        visible_fast_content._carly_prior = prior_fast_content
        fastpath._content = visible_fast_content

    # v6's missing-assistant repair has its own _content helper. Patch that too,
    # so even a client that omits Carly's immediately preceding question can
    # still recover a numeric monthly answer with the frontend suffix attached.
    if not getattr(commercial._content, "_carly_visible_text", False):
        prior_commercial_content = commercial._content

        def visible_commercial_content(message: Any) -> str:
            return _strip_frontend_context(prior_commercial_content(message))

        visible_commercial_content._carly_visible_text = True
        visible_commercial_content._carly_prior = prior_commercial_content
        commercial._content = visible_commercial_content

    # v7 decides whether stale shown_cars should be ignored by inspecting the
    # latest buyer turn. Make that decision on visible text as well.
    def latest_visible_user_text(messages: list[Any]) -> str:
        for message in reversed(list(messages or [])):
            if v7._role(message) == "user":
                return commercial._content(message).strip()
        return ""

    v7._latest_user_text = latest_visible_user_text


_install_visible_text_parser()
