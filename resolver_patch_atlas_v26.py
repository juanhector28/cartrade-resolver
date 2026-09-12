from pathlib import Path

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
marker = '# ATLAS_FRESHNESS_V1'

if marker not in s:
    old = 'from typing import Optional, List\n'
    new = 'from typing import Optional, List\nfrom .atlas_freshness_api import install as _install_atlas_freshness, freshness_cutoff_iso as _atlas_freshness_cutoff_iso\n'
    if old not in s:
        raise RuntimeError('freshness import anchor missing')
    s = s.replace(old, new, 1)

    old_cols = '"visible_damage_risk,damage_signals,vision_checked_at,listing_state,source,raw_payload"\n)'
    new_cols = '"visible_damage_risk,damage_signals,vision_checked_at,listing_state,source,raw_payload,last_seen_at"\n)'
    if old_cols not in s:
        raise RuntimeError('freshness CARLY_COLS anchor missing')
    s = s.replace(old_cols, new_cols, 1)

    old_query = 'supabase.table("scraped_listings").select(CARLY_COLS).eq("status", "staging")'
    new_query = 'supabase.table("scraped_listings").select(CARLY_COLS).eq("status", "staging").gte("last_seen_at", _atlas_freshness_cutoff_iso())'
    if old_query not in s:
        raise RuntimeError('freshness search anchor missing')
    s = s.replace(old_query, new_query)

    s += '\n\n# ATLAS_FRESHNESS_V1\n_install_atlas_freshness(app, supabase)\n'

p.write_text(s, encoding='utf-8')
print('Installed Atlas freshness v1')
