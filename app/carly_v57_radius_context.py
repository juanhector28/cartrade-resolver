"""Carly v57: keep frontend search radius out of buyer-intent semantics.

The web client appends location metadata such as ``radio = 100 km`` to the latest
user message. That number describes the MARKET SEARCH RADIUS, never the buyer's
daily driving. Older sanitizers did not match the frontend's ``radio =`` syntax,
so a model-only first turn such as ``Subaru Impreza`` could leak 100 km into the
LLM context and Carly could hallucinate ``100 km diarios``.

v57 fixes both boundaries:
1) remove every radius/distance clause from frontend metadata before any LLM sees
   it, while preserving city/country metadata;
2) make late intake helpers in v25/v26 read only visible buyer text, so the same
   hidden radius cannot become ``daily_km`` deterministically.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from . import main_guarded as guarded
from . import main_v25 as v25
from . import main_v26 as v26

log = logging.getLogger("carly.v57")

_CONTEXT_BLOCK_RE = re.compile(
    r"\s*\[CONTEXTO ACTIVO DE CARTRADE:.*$",
    re.I | re.S,
)
_RADIUS_WITH_DISTANCE_RE = re.compile(
    r"\b(?:radio|radius|rango)(?:\s+de\s+b[uú]squeda)?\b[^;|]*?"
    r"\b\d+(?:[.,]\d+)?\s*km\b",
    re.I,
)
_BARE_UI_DISTANCE_RE = re.compile(
    r"^\s*(?:[·|]\s*)?\d+(?:[.,]\d+)?\s*km\s*$",
    re.I,
)


def _strip_frontend_context(text: Any) -> str:
    return _CONTEXT_BLOCK_RE.sub("", str(text or "")).strip()


def _sanitize_frontend_meta_v57(items: list[str]) -> list[str]:
    """Preserve location/country clauses but never expose search-radius numbers."""
    cleaned: list[str] = []
    for item in items or []:
        # The frontend context is semicolon-delimited today. Treat every clause
        # independently so ``ubicación=...`` survives while ``radio = 100 km``
        # disappears completely.
        clauses = []
        for raw_clause in re.split(r"\s*;\s*", str(item or "")):
            clause = raw_clause.strip()
            if not clause:
                continue
            if _RADIUS_WITH_DISTANCE_RE.search(clause):
                continue
            if _BARE_UI_DISTANCE_RE.match(clause):
                continue
            # Defense in depth for variants embedded in a longer clause.
            clause = _RADIUS_WITH_DISTANCE_RE.sub("", clause)
            clause = re.sub(r"\s{2,}", " ", clause).strip(" ,·|")
            if clause:
                clauses.append(clause)
        if clauses:
            cleaned.append("; ".join(clauses))
    return cleaned


def _patch_visible_content(module: Any) -> None:
    prior = getattr(module, "_content", None)
    if prior is None or getattr(prior, "_carly_v57_visible_text", False):
        return

    def visible_content(message: Any) -> str:
        return _strip_frontend_context(prior(message))

    visible_content._carly_v57_visible_text = True
    visible_content._carly_v57_prior = prior
    module._content = visible_content


def install() -> None:
    guarded._sanitize_frontend_meta = _sanitize_frontend_meta_v57
    _patch_visible_content(v25)
    _patch_visible_content(v26)

    # Import-time regression guard for the exact live failure class.
    sample_meta = [
        "ubicación seleccionada por el usuario = Ciudad de Guatemala, Guatemala; "
        "país/código = gt; radio = 100 km. Usa esta ubicación como dato confirmado."
    ]
    safe = _sanitize_frontend_meta_v57(sample_meta)
    if any(re.search(r"\b100\s*km\b", row, re.I) for row in safe):
        raise RuntimeError("Carly v57 search-radius metadata leak regression")

    sample_messages = [
        {
            "role": "user",
            "content": (
                "Ir a la uni\n\n[CONTEXTO ACTIVO DE CARTRADE: ubicación seleccionada por el usuario = "
                "Ciudad de Guatemala, Guatemala; país/código = gt; radio = 100 km.]"
            ),
        }
    ]
    if v26._daily_km(sample_messages) is not None:
        raise RuntimeError("Carly v57 search radius became daily_km")

    log.warning("CARLY_V57 installed radius_metadata_isolation=true visible_intake_text=true")
