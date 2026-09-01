from pathlib import Path

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
marker = '# ATLAS_RESOLVER_RED_HARNESS_V12'
if marker not in s:
    old_num = '    m_num = re.search(r"\\$?\\s*(\\d{4,6})", t)\n'
    new_num = (
        '    m_year = re.search(r"\\b(19\\d{2}|20\\d{2})\\b", t)\n'
        '    m_num = re.search(r"\\$?\\s*(\\d{4,6})", t)\n'
        '    if m_num and m_year and m_num.group(1) == m_year.group(1):\n'
        '        m_num = None\n'
    )
    if old_num not in s:
        raise RuntimeError('v1.2 Carly year-query anchor missing')
    s = s.replace(old_num, new_num, 1)

    old_preflight = '''        ok = result.status_code == 200 and bool(result.json().get("ok"))\n        if not ok:\n            raise HTTPException(status_code=409, detail="fixture host unreachable from Resolver")\n        return {"ok": True, "fixture": True, "supabase": supabase is not None}\n'''
    new_preflight = '''        ok = result.status_code == 200 and bool(result.json().get("ok"))\n        if not ok:\n            raise HTTPException(status_code=409, detail="fixture host unreachable from Resolver")\n        if supabase is None:\n            raise HTTPException(status_code=409, detail="isolated Supabase/PostgREST is not connected")\n        return {"ok": True, "fixture": True, "supabase": True}\n'''
    if old_preflight not in s:
        raise RuntimeError('v1.2 Resolver preflight anchor missing')
    s = s.replace(old_preflight, new_preflight, 1)

    s += '\n# ATLAS_RESOLVER_RED_HARNESS_V12\n'

p.write_text(s, encoding='utf-8')
print('Installed Resolver red-harness v1.2 prerequisites')
