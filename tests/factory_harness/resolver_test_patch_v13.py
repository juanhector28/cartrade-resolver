from pathlib import Path

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
future = 'from __future__ import annotations\n'
# The production build-time patches may prepend test-only imports ahead of the
# original module docstring. Normalize the future import in the derived harness
# image only, so Resolver can boot without touching production source/runtime.
s = s.replace(future, '')
s = future + s.lstrip('\ufeff')
p.write_text(s, encoding='utf-8')
print('Normalized Resolver harness future-import ordering v1.3')
