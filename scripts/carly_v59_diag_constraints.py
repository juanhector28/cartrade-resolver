#!/usr/bin/env python3
from pprint import pprint
from app import main_v51
from app import carly_v59_demo_truth as v59

body={"country":"gt","messages":[{"role":"user","content":"Busco un Toyota SUV para mi familia, cuota hasta 450 al mes"}],"shown_cars":[]}
print("freshness_max_age_seconds", v59.v50.freshness_cutoff_iso.__module__)
c0=v59.v50._constraints_with_user_truth(body)
print("constraints_with_user_truth")
pprint(c0)
fast=v59.v50.v47.commercial.preview.extract_fast_profile(body["messages"],country="gt")
print("fast_profile")
pprint(fast)
c=v59.v50._merge_fast_constraints_v50(c0, fast or {})
brand=v59.v50._direct_requested_brand(v59.v31._text(body))
if brand: c["allowed_brands"]=[brand]
monthly=v59.v50.v28._extract_monthly(body)
if monthly is not None: c["monthly_max"]=float(monthly)
body_req=v59.v50.v46._explicit_body(v59.v31._text(body))
if body_req: c["require_body"]=body_req
print("final_constraints_before_retrieval")
pprint(c)
price_cap=None
if c.get("total_budget"):
    price_cap=float(c["total_budget"])
if c.get("monthly_max"):
    implied=float(c["monthly_max"])/0.0238*1.03
    price_cap=min(price_cap,implied) if price_cap else implied
print("calculated_price_cap",price_cap)
assert c.get("monthly_max")==450.0, c
assert c.get("total_budget") in (None,0), c
assert price_cap and price_cap>18000, price_cap
print("H2_RESULT=NOT_REPRODUCED")
