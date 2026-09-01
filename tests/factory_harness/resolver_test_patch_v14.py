from pathlib import Path

p = Path('/app/app/atlas_manifest_runner.py')
s = p.read_text(encoding='utf-8')
marker = '# ATLAS_RESOLVER_GOLDEN_DOM_DIAGNOSTICS_V14'
if marker not in s:
    old = '    out["_required_fields"] = required\n    return out\n'
    new = '''    out["_required_fields"] = required\n    if os.getenv("ATLAS_TEST_ENV") == "1" and "/golden-dom/listing-3" in str(url):\n        print(\n            "GOLDEN_DOM_RAW_EXTRACT=" + json.dumps(\n                {\n                    "url": url,\n                    "fields": fields,\n                    "required_fields": required,\n                    "raw_item_before_upsert": out,\n                },\n                sort_keys=True,\n                separators=(",", ":"),\n                default=str,\n            ),\n            flush=True,\n        )\n    return out\n'''
    if old not in s:
        raise RuntimeError('v1.4 raw-extract diagnostic anchor missing')
    s = s.replace(old, new, 1)
    s += '\n' + marker + '\n'
    p.write_text(s, encoding='utf-8')
print('Installed Resolver Golden DOM raw-extract diagnostics v1.4')
