from pathlib import Path

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
marker = '# ATLAS_CANONICAL_VERIFIER_V29'

if marker not in s:
    s += r'''

# ATLAS_CANONICAL_VERIFIER_V29
from app.atlas_canonical_verifier import install as _atlas_canonical_verifier_install

_atlas_canonical_verifier_install(app, supabase, _atlas_job_require_token)
print("ATLAS_CANONICAL_VERIFIER={'version':'v1','endpoint':'/atlas/canonical-verify'}", flush=True)
'''
    p.write_text(s, encoding='utf-8')

print('Installed Atlas canonical verifier v29')
