from pathlib import Path

path = Path('/app/app/atlas_manifest_runner.py')
if not path.exists():
    path = Path('app/atlas_manifest_runner.py')
text = path.read_text(encoding='utf-8')
old = '''    p = urlparse(url)\n    if p.scheme not in {"http", "https"}:\n        return None\n    if p.path.lower().endswith(_ASSET_EXT):\n        return None\n'''
new = '''    p = urlparse(url)\n    if p.scheme not in {"http", "https"}:\n        return None\n    host = p.netloc.lower().removeprefix("www.")\n    if host == "encuentra24.com" and "/autos-motos/" in p.path.lower():\n        return None\n    if p.path.lower().endswith(_ASSET_EXT):\n        return None\n'''
if new not in text:
    if old not in text:
        raise RuntimeError('Atlas v21 clean-url anchor missing')
    text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')
print('Applied Atlas v21 Encuentra24 car-route gate')
