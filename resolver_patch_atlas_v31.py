from pathlib import Path

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
marker = '# ATLAS_SEARCH_FRESHNESS_COUNTRY_V31'
if marker in s:
    print('Atlas search freshness country v31 already installed')
else:
    old_import = 'from .atlas_freshness_api import install as _install_atlas_freshness, freshness_cutoff_iso as _atlas_freshness_cutoff_iso\n'
    new_import = 'from .atlas_freshness_api import install as _install_atlas_freshness, freshness_cutoff_iso as _atlas_freshness_cutoff_iso, effective_search_country as _atlas_effective_search_country\n'
    if old_import not in s:
        raise RuntimeError('v31 freshness import anchor missing')
    s = s.replace(old_import, new_import, 1)

    route_anchor = '@app.post("/carly/search")\nasync def carly_search(body: CarlySearchRequest):\n'
    route_pos = s.find(route_anchor)
    if route_pos < 0:
        raise RuntimeError('v31 carly_search route anchor missing')
    next_route = s.find('\n@app.', route_pos + len(route_anchor))
    if next_route < 0:
        raise RuntimeError('v31 next route boundary missing')
    route = s[route_pos:next_route]

    old_query = 'supabase.table("scraped_listings").select(CARLY_COLS).eq("status", "staging").gte("last_seen_at", _atlas_freshness_cutoff_iso())'
    new_query = 'supabase.table("scraped_listings").select(CARLY_COLS).eq("status", "staging").gte("last_seen_at", _atlas_freshness_cutoff_iso(_atlas_effective_search_country(getattr(body, "country", None), getattr(body, "source_id", None))))'
    query_count = route.count(old_query)
    if query_count != 1:
        raise RuntimeError(f'v31 carly_search freshness anchor count={query_count}, expected 1')
    route = route.replace(old_query, new_query, 1)

    # Normalize explicit market ids before database equality filtering. Historical
    # source-scoped probes can omit country; their source_id still drives freshness.
    old_country = '    if body.country:\n        q = q.eq("country", body.country)\n'
    country_count = route.count(old_country)
    if country_count != 1:
        raise RuntimeError(f'v31 carly_search country anchor count={country_count}, expected 1')
    route = route.replace(
        old_country,
        '    if body.country:\n        q = q.eq("country", _atlas_effective_search_country(body.country, getattr(body, "source_id", None)))\n',
        1,
    )

    # Build-time negative controls: the live route must no longer use the
    # country-blind freshness call or the raw, case-sensitive country equality.
    if '_atlas_freshness_cutoff_iso())' in route:
        raise RuntimeError('v31 country-blind freshness survived in carly_search')
    if 'q = q.eq("country", body.country)' in route:
        raise RuntimeError('v31 raw country equality survived in carly_search')
    if '_atlas_effective_search_country(getattr(body, "country", None), getattr(body, "source_id", None))' not in route:
        raise RuntimeError('v31 effective country not bound to freshness')

    s = s[:route_pos] + route + s[next_route:]
    s += '\n\n# ATLAS_SEARCH_FRESHNESS_COUNTRY_V31\n'
    p.write_text(s, encoding='utf-8')
    print('Installed Atlas country-aware search freshness v31')
