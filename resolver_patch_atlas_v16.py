from pathlib import Path

rp = Path('/app/app/atlas_manifest_runner.py')
rs = rp.read_text(encoding='utf-8')
if '# ATLAS_CONTRACT_V16_BOOTSTRAP' not in rs:
    rs += r'''

# ATLAS_CONTRACT_V16_BOOTSTRAP
from .atlas_contract_v16 import install as _atlas_install_contract_v16
_atlas_install_contract_v16(globals())
'''
rp.write_text(rs, encoding='utf-8')

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
for old in (
    'atlas-manifest-v1', 'atlas-manifest-v1.1', 'atlas-manifest-v1.2',
    'atlas-manifest-v1.3', 'atlas-manifest-v1.4', 'atlas-manifest-v1.5'
):
    s = s.replace(f'"runner": "{old}"', '"runner": "atlas-manifest-v1.6"')
s = s.replace('"repair_version": "v1.5"', '"repair_version": "v1.6"')
if '"field_contract_v16": True' not in s:
    s = s.replace(
        '"vehicle_gate_v2": True,',
        '"vehicle_gate_v2": True,\n        "field_contract_v16": True,\n        "sample_price_contract": "native_plus_usd_v1",'
    )
for old in ('1.5.0', '1.6.0', '1.7.0', '1.8.0', '1.9.0', '1.10.0'):
    s = s.replace(f'version="{old}"', 'version="1.11.0"')
    s = s.replace(f'"version": "{old}"', '"version": "1.11.0"')
p.write_text(s, encoding='utf-8')
print('Applied Atlas runner v1.6 field/sample contracts; resolver version=1.11.0')
