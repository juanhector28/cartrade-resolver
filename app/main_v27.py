"""Carly v27: lender requirement bridge for Atlas Capital -> CarTrade -> Trust+."""
from __future__ import annotations

from . import main_v26 as v26
from . import trustplus_requirements as trustplus

app = v26.app
trustplus.init_db()
app.include_router(trustplus.router)
app.add_api_route("/hooks/trustplus", trustplus.trustplus_webhook, methods=["POST"])
