"""Carly v45: close the USD-prefix intake gap on the deterministic fast path.

Production already has a zero-token common-journey path. The remaining gap was
currency order: replies such as ``USD 600`` were not recognized as standalone
monthly answers even when Carly had just asked for the monthly payment. That
pushed an otherwise-complete family/SUV request back into the slower LLM path
and could cause a redundant budget question.

v45 changes parsing only. Ranking, safety gates, source truth, and v44 latency
profiling remain untouched.
"""
from __future__ import annotations

import logging
import re

from . import carly_fastpath as fastpath
from . import carly_preview_first as preview_first
from . import main_v44 as v44

app = v44.app
log = logging.getLogger("carly.fastpath.v45")

# Keep capture groups compatible with _monthly_from_messages():
#   1/2 = amount/suffix from explicit monthly phrasing
#   3/4 = amount/suffix after "cuota" / "mensualidad".
fastpath._MONTHLY_EXPLICIT = re.compile(
    rf"(?:(?:usd|us\$)\s*)?(?:\$\s*)?({fastpath._NUMBER})\s*(k|mil)?\s*"
    rf"(?:/\s*mes|al\s+mes|por\s+mes|mensuales?|mensual)\b|"
    rf"\b(?:cuota|mensualidad)\b[^\d$]{{0,25}}"
    rf"(?:(?:usd|us\$)\s*)?\$?\s*({fastpath._NUMBER})\s*(k|mil)?",
    re.I,
)

# Standalone answer after a monthly-payment question. Supports both currency
# orders: "USD 600", "$600", "600 USD", and plain "600".
fastpath._STANDALONE_MONEY = re.compile(
    rf"^\s*(?:(?:usd|us\$)\s*)?\$?\s*({fastpath._NUMBER})\s*(k|mil)?\s*"
    rf"(?:usd|dolares|dólares)?\s*$",
    re.I,
)

# Same currency-order repair for explicit total-price ceilings.
fastpath._PRICE_MAX = re.compile(
    rf"\b(?:max(?:imo)?|máximo|hasta|tope|techo|no\s+mas\s+de|no\s+más\s+de)\s*"
    rf"(?:de\s*)?(?:(?:usd|us\$)\s*)?\$?\s*({fastpath._NUMBER})\s*(k|mil)?\b",
    re.I,
)

# Keep preview policy aligned with the parser so "USD 600" counts as a real
# affordability signal instead of permitting a second blocker question.
preview_first._BUDGET_RE = re.compile(
    r"(?:\b(?:usd|us\$)\s*\$?\s*\d|" + preview_first._BUDGET_RE.pattern + r")",
    re.I,
)

try:
    v44.v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = (
        "commercial-v45-usd-prefix-fastpath"
    )
except Exception:
    pass

log.warning("CARLY_V45_FASTPATH installed usd_prefix_budget=true")
