from pathlib import Path

rp = Path('/app/app/atlas_manifest_runner.py')
rs = rp.read_text(encoding='utf-8')

if '# ATLAS_PHOTO_IDENTITY_V2_BOOTSTRAP' not in rs:
    rs += r'''

# ATLAS_PHOTO_IDENTITY_V2_BOOTSTRAP
from .atlas_photo_identity_v2 import install as _atlas_install_photo_identity_v2
_atlas_install_photo_identity_v2(globals())
'''

if '# ATLAS_VEHICLE_GATE_V2_BOOTSTRAP' not in rs:
    rs += r'''

# ATLAS_VEHICLE_GATE_V2_BOOTSTRAP
from .atlas_vehicle_gate_v2 import install as _atlas_install_vehicle_gate_v2
_atlas_install_vehicle_gate_v2(globals())
'''

rp.write_text(rs, encoding='utf-8')

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
for old in ('atlas-manifest-v1', 'atlas-manifest-v1.1', 'atlas-manifest-v1.2', 'atlas-manifest-v1.3', 'atlas-manifest-v1.4'):
    s = s.replace(f'"runner": "{old}"', '"runner": "atlas-manifest-v1.5"')

s = s.replace('"repair_version": "v1.4"', '"repair_version": "v1.5"')
if '"vehicle_gate_v2": True' not in s:
    s = s.replace(
        '"photo_recovery": True,',
        '"photo_recovery": True,\n        "photo_identity_gate_v2": True,\n        "vehicle_gate_v2": True,'
    )

for old in ('1.5.0', '1.6.0', '1.7.0', '1.8.0', '1.9.0'):
    s = s.replace(f'version="{old}"', 'version="1.10.0"')
    s = s.replace(f'"version": "{old}"', '"version": "1.10.0"')

p.write_text(s, encoding='utf-8')
print('Applied Atlas runner v1.5 vehicle/photo identity gates; resolver version=1.10.0')
