from pathlib import Path

# Atlas v20: treat Panamanian balboa as USD-parity for canonical staging price.
# This is deliberately narrow: other non-USD currencies still require an
# explicit ATLAS_FX_<CUR>_PER_USD rate and therefore remain fail-closed.
path = Path('/app/app/atlas_manifest_runner.py')
if not path.exists():
    path = Path('app/atlas_manifest_runner.py')

text = path.read_text(encoding='utf-8')
old = 'if cur in {"USD", "US$", "$"}:\n        return round(n, 2)'
new = 'if cur in {"USD", "US$", "$", "PAB", "B/.", "B/", "BALBOA", "BALBOAS"}:\n        return round(n, 2)'

if new not in text:
    if old not in text:
        raise RuntimeError('Atlas v20 currency-normalization anchor missing')
    text = text.replace(old, new, 1)

path.write_text(text, encoding='utf-8')
print('Applied Atlas v20 PAB/USD parity normalization')
