from pathlib import Path


p = Path("/app/app/main.py")
s = p.read_text(encoding="utf-8")

marker = "# ATLAS_PUBLISH_API_V1"
if marker not in s:
    s += r'''

# ATLAS_PUBLISH_API_V1
from .atlas_publish_api import install as _atlas_install_publish_api
_atlas_install_publish_api(app=app, supabase=supabase)
'''

if '"publish_api": True' not in s:
    s = s.replace(
        '"inventory_read_api": True,',
        '"inventory_read_api": True,\n        "publish_api": True,\n        "publish_collision_policy": "production_wins_fail_closed",',
    )

s = s.replace('version="1.12.0"', 'version="1.13.0"')
s = s.replace('"version": "1.12.0"', '"version": "1.13.0"')

p.write_text(s, encoding="utf-8")
print("Installed fail-closed Atlas publish API; resolver version=1.13.0")
