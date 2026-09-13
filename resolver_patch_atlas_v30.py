from pathlib import Path

p = Path('/app/app/atlas_manifest_runner.py')
s = p.read_text(encoding='utf-8')

anchor = '''            "sample": [\n                {k: v for k, v in item.items() if not k.startswith("_")}\n                for item in valid[:5]\n            ],'''
replacement = '''            # `items` is the complete validated harvest payload consumed by Atlas.\n            # `sample` remains intentionally capped for diagnostics/semantic checks.\n            "items": [\n                {k: v for k, v in item.items() if not k.startswith("_")}\n                for item in valid\n            ],\n            "sample": [\n                {k: v for k, v in item.items() if not k.startswith("_")}\n                for item in valid[:5]\n            ],'''

if anchor not in s:
    if '"items": [' in s and 'for item in valid' in s:
        print('Atlas full-items response already installed')
        raise SystemExit(0)
    raise RuntimeError('Atlas harvest response anchor missing')

s = s.replace(anchor, replacement, 1)
p.write_text(s, encoding='utf-8')
print('Installed Atlas full harvest response: items=all valid, sample<=5')
