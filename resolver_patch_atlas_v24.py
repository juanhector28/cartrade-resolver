from pathlib import Path
import re

p = Path('/app/app/main.py')
s = p.read_text(encoding='utf-8')
marker = '# CARLY_MAKE_MODEL_INTENT_V24'

if marker not in s:
    # 1) Intent gains an explicit model dimension.
    intent_old = '''class Intent(BaseModel):
    body_types: List[str] = []
    price_max: Optional[int] = None
    price_min: Optional[int] = None
    transmission: Optional[str] = None
    make: Optional[str] = None
    use: Optional[str] = None
    newest_first: bool = False
'''
    intent_new = '''class Intent(BaseModel):
    body_types: List[str] = []
    price_max: Optional[int] = None
    price_min: Optional[int] = None
    transmission: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    use: Optional[str] = None
    newest_first: bool = False
'''
    if intent_old not in s:
        raise RuntimeError('v24 Intent anchor missing')
    s = s.replace(intent_old, intent_new, 1)

    # 2) Conservative make+model extraction. We only infer a model when a known
    #    make is present, then strip shopping/usage/market qualifiers.
    helper_anchor = '\n\ndef parse_intent(text: str) -> Intent:\n'
    helper = r'''

_CARLY_MODEL_NOISE = {
    "auto", "autos", "carro", "carros", "vehiculo", "vehiculos", "vehículo", "vehículos",
    "usado", "usados", "seminuevo", "seminuevos", "nuevo", "nuevos",
    "automatico", "automatica", "automático", "automática", "manual", "mecanico", "mecanica",
    "mecánico", "mecánica", "diesel", "gasolina", "hibrido", "hibrida", "híbrido", "híbrida",
    "electrico", "electrica", "eléctrico", "eléctrica",
    "suv", "crossover", "pickup", "sedan", "camioneta", "4x4", "4x2",
    "familia", "familiar", "hijos", "esposa", "trabajo", "carga", "negocio", "finca",
    "primer", "economico", "economica", "económico", "económica", "barato", "barata",
    "lujo", "premium", "full", "equipado", "equipada",
    "menos", "mas", "más", "bajo", "debajo", "arriba", "desde", "hasta", "entre",
    "con", "sin", "para", "de", "del", "la", "el", "un", "una", "y", "en",
    "guatemala", "salvador", "panama", "panamá", "costa", "rica",
    "gt", "sv", "cr", "pa",
}


def _extract_model_candidate(text: str, make: str | None) -> str | None:
    if not make:
        return None
    t = _norm(text)

    # Remove the make once. Mercedes-Benz commonly appears as two tokens while
    # the legacy make detector reports just "mercedes".
    if make == "mercedes":
        t = re.sub(r"\bmercedes(?:[-\s]+benz)?\b", " ", t, count=1)
    else:
        make_expr = r"\b" + re.escape(_norm(make)).replace(r"\ ", r"[-\s]+") + r"\b"
        t = re.sub(make_expr, " ", t, count=1)

    # Remove years, prices/budgets and mileage-like numeric qualifiers before
    # token extraction. Alpha-numeric model names such as X5, CX-5, Q7 survive.
    t = re.sub(r"\b(?:19[89]\d|20[0-3]\d)\b", " ", t)
    t = re.sub(r"\$\s*\d[\d,.]*", " ", t)
    t = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:k|mil|km|kms|kilometros|kilómetros)\b", " ", t)

    tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", t)
    clean = [tok for tok in tokens if tok not in _CARLY_MODEL_NOISE]
    if not clean:
        return None

    # Keep multi-word model families (Land Cruiser Prado, Grand Cherokee, etc.)
    # while putting a hard ceiling on accidental prose.
    candidate = " ".join(clean[:4]).strip()
    return candidate or None


def _model_ilike_pattern(model: str) -> str:
    # Formatting varies by source (CR-V vs CRV, CX-5 vs CX 5). Matching ordered
    # alpha-numeric chunks keeps make+model strict without depending on punctuation.
    chunks = re.findall(r"[a-z0-9]+", _norm(model))
    return "%" + "%".join(chunks) + "%" if chunks else "%"
'''
    if helper_anchor not in s:
        raise RuntimeError('v24 parse_intent anchor missing')
    s = s.replace(helper_anchor, helper + helper_anchor, 1)

    # 3) Derive model after the existing make detector.
    make_old = '''    for mk in MAKES:
        if mk in t:
            it.make = mk
            break
    return it
'''
    make_new = '''    for mk in sorted(MAKES, key=len, reverse=True):
        if mk in t:
            it.make = mk
            break
    it.model = _extract_model_candidate(text, it.make)
    return it
'''
    if make_old not in s:
        raise RuntimeError('v24 make detection anchor missing')
    s = s.replace(make_old, make_new, 1)

    # 4) Search contract accepts an explicit model too. Explicit API filters win
    #    over free-text inference, which lets product UIs become even stricter later.
    req_anchor = '''    addressable_only: bool = True
    source_id: Optional[str] = None
    manifest_version: Optional[int] = None
'''
    req_new = '''    addressable_only: bool = True
    model: Optional[str] = None
    source_id: Optional[str] = None
    manifest_version: Optional[int] = None
'''
    if req_anchor not in s:
        raise RuntimeError('v24 CarlySearchRequest v19 anchor missing')
    s = s.replace(req_anchor, req_new, 1)

    parse_anchor = '''    it = parse_intent(body.q)
    q = supabase.table("scraped_listings").select(CARLY_COLS)
'''
    parse_new = '''    it = parse_intent(body.q)
    if body.model:
        it.model = str(body.model).strip() or None
    q = supabase.table("scraped_listings").select(CARLY_COLS)
'''
    if parse_anchor not in s:
        raise RuntimeError('v24 search parse anchor missing')
    s = s.replace(parse_anchor, parse_new, 1)

    filter_anchor = '''    if it.make:
        q = q.ilike("make", f"%{it.make}%")
    if it.price_max:
'''
    filter_new = '''    if it.make:
        q = q.ilike("make", f"%{it.make}%")
    if it.model:
        q = q.ilike("model", _model_ilike_pattern(it.model))
    if it.price_max:
'''
    if filter_anchor not in s:
        raise RuntimeError('v24 make filter anchor missing')
    s = s.replace(filter_anchor, filter_new, 1)

    s += '\n' + marker + '\n'
    p.write_text(s, encoding='utf-8')

# Build-time contract checks: fail the image if extraction regresses.
src = p.read_text(encoding='utf-8')
assert 'model: Optional[str] = None' in src
assert 'q = q.ilike("model", _model_ilike_pattern(it.model))' in src
assert '_extract_model_candidate(text, it.make)' in src

print('Installed Carly v24 strict make+model intent filtering')
