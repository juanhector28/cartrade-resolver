from pathlib import Path

p = Path("/app/app/main.py")
if not p.exists():
    p = Path("app/main.py")

s = p.read_text(encoding="utf-8")
marker = "# CARLY_SEARCH_BODY_FALLBACK_V60"

if marker in s:
    print("Carly search body fallback v60 already installed")
    raise SystemExit(0)

route_anchor = '@app.post("/carly/search")\nasync def carly_search(body: CarlySearchRequest):\n'
route_pos = s.find(route_anchor)
if route_pos < 0:
    raise RuntimeError("carly_search route anchor missing")
next_route = s.find("\n@app.", route_pos + len(route_anchor))
if next_route < 0:
    raise RuntimeError("carly_search next route boundary missing")
route = s[route_pos:next_route]

sql_filter = '''    if it.body_types:
        q = q.in_("body_type", it.body_types)
'''
if route.count(sql_filter) != 1:
    raise RuntimeError(f"expected one SQL body filter, got {route.count(sql_filter)}")
route = route.replace(
    sql_filter,
    '''    # CARLY_SEARCH_BODY_FALLBACK_V60
    # Do not filter body_type in SQL. Certified Atlas rows can legitimately have
    # body_type=NULL even when make/model is sufficient to classify the vehicle.
    # Filter the bounded pool below after deterministic model-based inference.
''',
    1,
)

pool_anchor = '''    try:
        pool = q.limit(300).execute().data or []
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Supabase query failed: {e!s}")

    total_matching = len(pool)            # for the transparency line ("de N, estos M")
'''
if route.count(pool_anchor) != 1:
    raise RuntimeError(f"pool anchor count={route.count(pool_anchor)}, expected 1")
pool_new = '''    try:
        pool = q.limit(300).execute().data or []
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Supabase query failed: {e!s}")

    if it.body_types:
        wanted_bodies = {str(x or "").strip().lower() for x in it.body_types if x}
        filtered_pool = []
        for car in pool:
            raw_body = str(car.get("body_type") or "").strip().lower()
            effective_body = raw_body or classify_body_type(car.get("model"), None)
            effective_body = {
                "hatchback": "hatch",
                "crossover": "suv",
                "minivan": "van",
            }.get(effective_body, effective_body)
            if effective_body:
                car["body_type"] = effective_body
            if effective_body in wanted_bodies:
                filtered_pool.append(car)
        pool = filtered_pool

    total_matching = len(pool)            # for the transparency line ("de N, estos M")
'''
route = route.replace(pool_anchor, pool_new, 1)

if 'q = q.in_("body_type", it.body_types)' in route:
    raise RuntimeError("SQL body_type filter survived v60")
if "classify_body_type(car.get(\"model\"), None)" not in route:
    raise RuntimeError("model-based body fallback missing")

s = s[:route_pos] + route + s[next_route:]
s += "\n\n# CARLY_SEARCH_BODY_FALLBACK_V60\n"
p.write_text(s, encoding="utf-8")
print("Installed Carly search body fallback v60")
