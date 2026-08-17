from pathlib import Path

rp = Path('/app/app/atlas_manifest_runner.py')
rs = rp.read_text(encoding='utf-8')
bootstrap = '# ATLAS_PHOTO_REPAIR_BOOTSTRAP_V1'
if bootstrap not in rs:
    rs += r'''

# ATLAS_PHOTO_REPAIR_BOOTSTRAP_V1
from .atlas_photo_repair import install as _atlas_install_photo_repair
_atlas_install_photo_repair(globals())
'''
rp.write_text(rs, encoding='utf-8')

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
for old in ('atlas-manifest-v1', 'atlas-manifest-v1.1', 'atlas-manifest-v1.2', 'atlas-manifest-v1.3'):
    s = s.replace(f'"runner": "{old}"', '"runner": "atlas-manifest-v1.4"')
if '"photo_recovery": True' not in s:
    s = s.replace(
        '"auto_repair": True,',
        '"auto_repair": True,\n        "photo_recovery": True,\n        "repair_version": "v1.4",'
    )
for old in ('1.5.0', '1.6.0', '1.7.0', '1.8.0'):
    s = s.replace(f'version="{old}"', 'version="1.9.0"')
    s = s.replace(f'"version": "{old}"', '"version": "1.9.0"')
p.write_text(s, encoding='utf-8')
print('Applied Atlas runner v1.4 generic photo recovery; resolver version=1.9.0')
