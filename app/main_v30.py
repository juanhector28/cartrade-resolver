"""Carly v30: intake intent hotfix for demo-critical explicit use cases."""
from __future__ import annotations

import re

from . import main_v29 as v29
from . import carly_fastpath as fastpath

# Teach the deterministic intake gate that these phrases already answer
# "what will you use the car for?" so Carly never asks the same question again.
_DEMO_INTENTS = (
    ("daily_commute", re.compile(r"\b(?:universidad|universitario|universitaria|campus|facultad|estudiante|estudiar)\b", re.I), "ciudad"),
    ("work_vehicle", re.compile(r"\b(?:finca|fincas|campo|rural|agricultura|ganaderia|ganadería)\b", re.I), "mixto"),
)

# _infer_job reads this global dynamically, so prepending is enough to fix every
# downstream deterministic intake caller without rewriting the large parser.
existing = tuple(getattr(fastpath, "_JOB_PATTERNS", ()))
fastpath._JOB_PATTERNS = _DEMO_INTENTS + existing

app = v29.app

try:
    v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v30-intent-hotfix"
except Exception:
    pass
