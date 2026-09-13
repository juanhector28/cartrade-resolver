from pathlib import Path

# Preserve v30 full-items harvest response patch.
p = Path('/app/app/atlas_manifest_runner.py')
s = p.read_text(encoding='utf-8')

anchor = '''            "sample": [\n                {k: v for k, v in item.items() if not k.startswith("_")}\n                for item in valid[:5]\n            ],'''
replacement = '''            # `items` is the complete validated harvest payload consumed by Atlas.\n            # `sample` remains intentionally capped for diagnostics/semantic checks.\n            "items": [\n                {k: v for k, v in item.items() if not k.startswith("_")}\n                for item in valid\n            ],\n            "sample": [\n                {k: v for k, v in item.items() if not k.startswith("_")}\n                for item in valid[:5]\n            ],'''

if anchor not in s:
    if '"items": [' in s and 'for item in valid' in s:
        print('Atlas full-items response already installed')
    else:
        raise RuntimeError('Atlas harvest response anchor missing')
else:
    s = s.replace(anchor, replacement, 1)
    p.write_text(s, encoding='utf-8')
    print('Installed Atlas full harvest response: items=all valid, sample<=5')

# GT_DEMO_CERTIFIED_BOUNDARY_V1
# Production demo boundary: GT Carly may read only the five audited staging sources.
p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')

const_marker = '# GT_DEMO_CERTIFIED_BOUNDARY_V1'
if const_marker not in s:
    route_anchor = '''@app.post("/carly/search")\nasync def carly_search(body: CarlySearchRequest):\n'''
    if route_anchor not in s:
        raise RuntimeError('carly_search anchor missing')
    const = '''# GT_DEMO_CERTIFIED_BOUNDARY_V1\nGT_DEMO_CERTIFIED_SOURCES = [\n    "atlas:www.agautoventas.com",\n    "atlas:autogogt.com",\n    "atlas:hgmotors.movilauto.com",\n    "atlas:movilauto.com",\n    "atlas:www.enlacesautomotrices.com",\n]\n\n\n'''
    s = s.replace(route_anchor, const + route_anchor, 1)

    # v19 installs source_id provenance filtering before this patch runs, so anchor
    # immediately before that block rather than against the pre-v19 source form.
    search_anchor = '''    if body.country:\n        q = q.eq("country", body.country)\n    if body.source_id:\n'''
    search_new = '''    if body.country:\n        q = q.eq("country", body.country)\n    if (body.country or "").lower() == "gt":\n        q = q.eq("status", "staging").in_("source", GT_DEMO_CERTIFIED_SOURCES)\n    if body.source_id:\n'''
    if search_anchor not in s:
        raise RuntimeError('carly_search post-v19 country filter anchor missing')
    s = s.replace(search_anchor, search_new, 1)

    chat_anchor = '''        if country:\n            q = q.eq("country", country)\n        if profile.max_monthly:\n'''
    chat_new = '''        if country:\n            q = q.eq("country", country)\n        if (country or "").lower() == "gt":\n            q = q.in_("source", GT_DEMO_CERTIFIED_SOURCES)\n        if profile.max_monthly:\n'''
    if chat_anchor not in s:
        raise RuntimeError('carly chat inventory country filter anchor missing')
    s = s.replace(chat_anchor, chat_new, 1)

    if s.count('GT_DEMO_CERTIFIED_SOURCES') != 3:
        raise RuntimeError('unexpected GT boundary reference count')
    if 'q = q.eq("status", "staging").in_("source", GT_DEMO_CERTIFIED_SOURCES)' not in s:
        raise RuntimeError('search staging+allowlist boundary missing')
    if 'q = q.in_("source", GT_DEMO_CERTIFIED_SOURCES)' not in s:
        raise RuntimeError('chat allowlist boundary missing')

    p.write_text(s, encoding='utf-8')
    print('Installed GT_DEMO_CERTIFIED_BOUNDARY_V1: 5-source staging allowlist')
else:
    print('GT demo certified boundary already installed')
