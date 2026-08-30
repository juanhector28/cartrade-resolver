"""Carly v20: deterministic intake-state hardening.

The intake state must never ask again for a field the buyer already answered in
an earlier turn. The inherited fastpath already persists history, but its intent
vocabulary missed common natural-language answers such as finca, carro familiar,
and trips to the beach. Those misses made a known primary use look unknown and
caused Carly to repeat the same question.

This patch extends the deterministic intent vocabulary before the inherited app
serves requests. No extra LLM calls are introduced.
"""
from __future__ import annotations

import re

from . import carly_fastpath
from . import main_v19 as v19

# Common answers that semantically satisfy "¿para qué usarías el carro?".
# These are deliberately broad enough to capture normal buyer language while
# remaining useful for ranking. Earlier user turns remain part of the state, so a
# later "ya te lo dije" cannot erase an already-known intent.
_FAMILY_LEISURE_INTENT = (
    "family_transport",
    re.compile(
        r"\b(?:carro|auto|veh[ií]culo)?\s*familiar\b|"
        r"\b(?:familia|familias|playa|vacaciones|paseos? familiares?|viajes? familiares?)\b",
        re.I,
    ),
    "familia",
)

_RURAL_INTENT = (
    "work_vehicle",
    re.compile(
        r"\b(?:finca|fincas|granja|hacienda|parcela|terreno|campo|zona rural|"
        r"camino(?:s)? de tierra|terracer[ií]a|rural)\b",
        re.I,
    ),
    "trabajo",
)

for intent in (_FAMILY_LEISURE_INTENT, _RURAL_INTENT):
    if not any(getattr(p, "pattern", "") == intent[1].pattern for _, p, _ in carly_fastpath._JOB_PATTERNS):
        carly_fastpath._JOB_PATTERNS = (intent,) + tuple(carly_fastpath._JOB_PATTERNS)

app = v19.app
commercial = v19.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v20-intake-state-memory"
