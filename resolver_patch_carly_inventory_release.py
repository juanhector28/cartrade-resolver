"""Retire the GT demo and freshness restrictions on Carly, after legacy patches."""
from pathlib import Path

p = Path('/app/app/main_v50.py')
s = p.read_text()
boundary = '''        if (country or "").lower() == "gt":
            q = q.in_("source", GT_DEMO_CERTIFIED_SOURCES)

'''
if s.count(boundary) != 1:
    raise RuntimeError('Expected one v50 GT demo boundary')
s = s.replace(boundary, '', 1)
if '.gte("last_seen_at"' in s:
    raise RuntimeError('Historical focused retrieval still has a freshness gate')
p.write_text(s)

p = Path('/app/app/main.py')
s = p.read_text()
for boundary in (
    '''    if (body.country or "").lower() == "gt":
        q = q.eq("status", "staging").in_("source", GT_DEMO_CERTIFIED_SOURCES)
''',
    '''        if (country or "").lower() == "gt":
            q = q.in_("source", GT_DEMO_CERTIFIED_SOURCES)
''',
):
    if s.count(boundary) != 1:
        raise RuntimeError('Expected a legacy GT demo boundary')
    s = s.replace(boundary, '', 1)
for suffix in (
    '.gte("last_seen_at", _atlas_freshness_cutoff_iso())',
    '.gte("last_seen_at", _atlas_freshness_cutoff_iso(_atlas_effective_search_country(getattr(body, "country", None), getattr(body, "source_id", None))))',
):
    if s.count(suffix) != 1:
        raise RuntimeError('Expected a legacy Carly freshness gate')
    s = s.replace(suffix, '', 1)
query = 'supabase.table("scraped_listings").select(CARLY_COLS).eq("status", "staging")'
if s.count(query) != 2:
    raise RuntimeError('Expected both legacy Carly publication queries')
s = s.replace(query, query + '.eq("listing_state", "indexed").eq("is_addressable", True)')
p.write_text(s)
print('Carly historical inventory enabled across countries and sources')
