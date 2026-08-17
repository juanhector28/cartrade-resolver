from pathlib import Path

# Install the generic semantic repair layer after the v1.2 semantic gate has
# been appended by resolver_patch_atlas.py.
rp = Path('/app/app/atlas_manifest_runner.py')
rs = rp.read_text(encoding='utf-8')
bootstrap = '# ATLAS_AUTO_REPAIR_BOOTSTRAP_V1'
if bootstrap not in rs:
    rs += r'''

# ATLAS_AUTO_REPAIR_BOOTSTRAP_V1
from .atlas_auto_repair import install as _atlas_install_auto_repair
_atlas_install_auto_repair(globals())
'''
rp.write_text(rs, encoding='utf-8')

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')

# Surface the upgraded runner/gate in the public status endpoint.
for old in ('atlas-manifest-v1', 'atlas-manifest-v1.1', 'atlas-manifest-v1.2'):
    s = s.replace(f'"runner": "{old}"', '"runner": "atlas-manifest-v1.3"')
if '"auto_repair": True' not in s:
    s = s.replace(
        '"semantic_activation_gate": True,',
        '"semantic_activation_gate": True,\n        "auto_repair": True,\n        "fx_policy": "official_or_explicit_override",'
    )

# Defense in depth. Carly chat already requires status=staging; make the direct
# /carly/search endpoint enforce the same condition even when is_addressable is
# a generated column.
if '# ATLAS_CARLY_SHADOW_ISOLATION_V1' not in s:
    old = '''    q = supabase.table("scraped_listings").select(CARLY_COLS)

    if body.addressable_only:
'''
    new = '''    q = supabase.table("scraped_listings").select(CARLY_COLS).eq("status", "staging")  # ATLAS_CARLY_SHADOW_ISOLATION_V1

    if body.addressable_only:
'''
    s = s.replace(old, new)

for old in ('1.5.0', '1.6.0', '1.7.0'):
    s = s.replace(f'version="{old}"', 'version="1.8.0"')
    s = s.replace(f'"version": "{old}"', '"version": "1.8.0"')

p.write_text(s, encoding='utf-8')
print('Applied Atlas runner v1.3 auto-repair bootstrap; resolver version=1.8.0')
