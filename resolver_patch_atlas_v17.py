from pathlib import Path


p = Path("/app/app/main.py")
s = p.read_text(encoding="utf-8")

marker = "# ATLAS_INVENTORY_READ_API_V1"
if marker not in s:
    s += r'''

# ATLAS_INVENTORY_READ_API_V1
from .atlas_inventory_api import install as _atlas_install_inventory_api
_atlas_install_inventory_api(app=app, supabase=supabase)
'''

if '"inventory_read_api": True' not in s:
    s = s.replace(
        '"field_contract_v16": True,',
        '"field_contract_v16": True,\n        "inventory_read_api": True,\n        "inventory_read_mode": "shadow_only",',
    )

s = s.replace('version="1.11.0"', 'version="1.12.0"')
s = s.replace('"version": "1.11.0"', '"version": "1.12.0"')

p.write_text(s, encoding="utf-8")
print("Installed authenticated shadow inventory read API; resolver version=1.12.0")
