from pathlib import Path

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
marker = '# ATLAS_REFRESH_ORCHESTRATOR_V32'

if marker not in s:
    s += r'''

# ATLAS_REFRESH_ORCHESTRATOR_V32
from .atlas_refresh_orchestrator import install as _install_atlas_refresh_orchestrator
_install_atlas_refresh_orchestrator(
    app=app,
    supabase=supabase,
    runner=_atlas_manifest_runner,
    require_token=_require_atlas_bridge_token,
)
'''

for old, new in (
    ('version="1.17.0"', 'version="1.18.0"'),
    ('"version": "1.17.0"', '"version": "1.18.0"'),
):
    s = s.replace(old, new)

p.write_text(s, encoding='utf-8')
print('Installed Atlas refresh orchestrator v32')
