from pathlib import Path

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
marker = '# GT_DEMO_CERTIFIED_BOUNDARY_V1'
if marker in s:
    raise RuntimeError('GT demo certified boundary already installed')

anchor = '''@app.post("/carly/search")\nasync def carly_search(body: CarlySearchRequest):\n'''
if anchor not in s:
    raise RuntimeError('carly_search anchor missing')

const = '''# GT_DEMO_CERTIFIED_BOUNDARY_V1\nGT_DEMO_CERTIFIED_SOURCES = [\n    "atlas:www.agautoventas.com",\n    "atlas:autogogt.com",\n    "atlas:hgmotors.movilauto.com",\n    "atlas:movilauto.com",\n    "atlas:www.enlacesautomotrices.com",\n]\n\n\n'''
s = s.replace(anchor, const + anchor, 1)

search_anchor = '''    if body.country:\n        q = q.eq("country", body.country)\n    if it.body_types:\n'''
search_new = '''    if body.country:\n        q = q.eq("country", body.country)\n    if (body.country or "").lower() == "gt":\n        q = q.eq("status", "staging").in_("source", GT_DEMO_CERTIFIED_SOURCES)\n    if it.body_types:\n'''
if search_anchor not in s:
    raise RuntimeError('carly_search country filter anchor missing')
s = s.replace(search_anchor, search_new, 1)

chat_anchor = '''        if country:\n            q = q.eq("country", country)\n        if profile.max_monthly:\n'''
chat_new = '''        if country:\n            q = q.eq("country", country)\n        if (country or "").lower() == "gt":\n            q = q.in_("source", GT_DEMO_CERTIFIED_SOURCES)\n        if profile.max_monthly:\n'''
if chat_anchor not in s:
    raise RuntimeError('carly chat inventory country filter anchor missing')
s = s.replace(chat_anchor, chat_new, 1)

# Fail-closed build assertions: both GT search paths must carry the certified boundary.
if s.count('GT_DEMO_CERTIFIED_SOURCES') != 3:
    raise RuntimeError('unexpected GT boundary reference count')
if 'q = q.eq("status", "staging").in_("source", GT_DEMO_CERTIFIED_SOURCES)' not in s:
    raise RuntimeError('search staging+allowlist boundary missing')
if 'q = q.in_("source", GT_DEMO_CERTIFIED_SOURCES)' not in s:
    raise RuntimeError('chat allowlist boundary missing')

p.write_text(s, encoding='utf-8')
print('GT_DEMO_CERTIFIED_BOUNDARY_V1 installed')
