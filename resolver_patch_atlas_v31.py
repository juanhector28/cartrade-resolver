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

    old_query = 'supabase.table("scraped_listings").select(CARLY_COLS).eq("status", "staging").gte("last_seen_at", _atlas_freshness_cutoff_iso())'
    new_query = 'supabase.table("scraped_listings").select(CARLY_COLS).eq("status", "staging").gte("last_seen_at", _atlas_freshness_cutoff_iso(_atlas_effective_search_country(getattr(body, "country", None), getattr(body, "source_id", None))))'
    count = s.count(old_query)
    if count != 1:
        raise RuntimeError(f'v31 freshness query anchor count={count}, expected 1')
    s = s.replace(old_query, new_query, 1)

    # Normalize the explicit market before applying the database equality filter.
    # The frontend normally sends lower-case market ids, but the serving contract
    # should not silently return zero if an operator/probe sends `GT`.
    route_anchor = '@app.post("/carly/search")\nasync def carly_search(body: CarlySearchRequest):\n'
    route_pos = s.find(route_anchor)
    if route_pos < 0:
        raise RuntimeError('v31 carly_search route anchor missing')
    tail = s[route_pos:]
    old_country = '    if body.country:\n        q = q.eq("country", body.country)\n'
    if old_country not in tail:
        raise RuntimeError('v31 country filter anchor missing')
    tail = tail.replace(old_country, '    if body.country:\n        q = q.eq("country", _atlas_effective_search_country(body.country, getattr(body, "source_id", None)))\n', 1)
    s = s[:route_pos] + tail

    s += '\n\n# ATLAS_SEARCH_FRESHNESS_COUNTRY_V31\n'
    p.write_text(s, encoding='utf-8')
    print('Installed Atlas country-aware search freshness v31')
