"""Carly v20: intake state hardening for rural/finca journeys.

The existing fastpath correctly persists budget and known usage across turns, but
'finca' / rural-access language was not classified as intent. That left Carly in
a loop asking the same primary-use question even after the buyer answered it.

This patch extends the deterministic intent vocabulary before the inherited app
serves requests. No extra LLM calls are introduced.
"""
from __future__ import annotations

import re

from . import carly_fastpath
from . import main_v19 as v19

# A buyer saying they need the vehicle to reach/use a finca, farm, rural property,
# dirt road, or countryside has already answered the primary-use question. Treat
# this conservatively as a work/rural vehicle so the state machine advances.
_RURAL_INTENT = (
    "work_vehicle",
    re.compile(
        r"\b(?:finca|fincas|granja|hacienda|parcela|terreno|campo|zona rural|"
        r"camino(?:s)? de tierra|terracer[ií]a|rural)\b",
        re.I,
    ),
    "trabajo",
)

if not any(getattr(p, "pattern", "") == _RURAL_INTENT[1].pattern for _, p, _ in carly_fastpath._JOB_PATTERNS):
    carly_fastpath._JOB_PATTERNS = (_RURAL_INTENT,) + tuple(carly_fastpath._JOB_PATTERNS)

app = v19.app
commercial = v19.commercial
commercial.RUNTIME_COMPOSITION = "commercial-v20-intake-state-rural"
