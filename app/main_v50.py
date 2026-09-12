"""Carly v50: bound legacy fallback retrieval.

v47 eliminated duplicate broad ranking for common deterministic journeys, but
nuanced requests can still fall through the inherited v31 route and rank up to
900 rows before the authoritative focused rebuild. v46 already has a safe
preselection policy for interactive ranking; v50 applies that same bounded
retrieval to the inherited v31 query path as well.

Exact-model searches remain unbounded by this layer.
"""
from __future__ import annotations

from . import main_v49 as v49

app = v49.app
v48 = v49.v48
v47 = v48.v47
v46 = v47.v46
v44 = v47.v44
v31 = v46.v31

_ORIG_V31_QUERY = v31._query_rows


def _bounded_legacy_query(c, country):
    rows = _ORIG_V31_QUERY(c, country)
    return v46._cheap_preselect(rows, c)


# The inherited v31 fallback resolves this symbol dynamically.
v31._query_rows = _bounded_legacy_query

try:
    v47.v44.v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = (
        "commercial-v50-bounded-legacy-retrieval"
    )
except Exception:
    pass
