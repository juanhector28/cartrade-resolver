"""
carly_ranking.py  —  Ranking engine V2 de Carly (optimizado)

Cambios vs V1:
  (11) Normalizacion robusta de datos sucios (body_type "hatch", trans
       "Automática" con tilde/mayuscula) ANTES de cualquier match.
  (1)  Factor "modernidad" (premia años recientes).
  (2)  economy_score recalibrado para que discrimine.
  (3)  Penalizacion de km alto mas fuerte (en confiabilidad efectiva).
  (4)  Diversidad en el top (no clones del mismo make+body).
  (7)  Fairness visible: cuanto bajo/sobre mercado, numero y texto.
  (8)  "Lo que debes saber": contra honesta por auto.
  (9)  Inspeccion: que revisar segun año/km, sin alarmar.
Filosofia intacta: filtrar duro, puntuar suave, pesos por conversacion.
"""

from dataclasses import dataclass, field
from typing import Optional

CURRENT_YEAR = 2026

# ──────────────────────────── TABLAS ───────────────────────────────
RELIABILITY_BY_MODEL = {
    ("toyota","rav4"):93,("toyota","yaris"):90,("toyota","corolla"):95,
    ("toyota","corolla cross"):92,("toyota","hilux"):94,("toyota","fortuner"):90,
    ("toyota","land cruiser"):93,("toyota","prado"):91,("toyota","4runner"):92,
    ("toyota","echo"):84,("toyota","tacoma"):92,
    ("hyundai","tucson"):80,("hyundai","accent"):81,("hyundai","santa fe"):79,
    ("hyundai","elantra"):80,("hyundai","grand i10"):78,("hyundai","creta"):80,
    ("kia","sportage"):79,("kia","rio"):80,("kia","sorento"):78,
    ("kia","picanto"):79,("kia","seltos"):79,
    ("nissan","qashqai"):76,("nissan","kicks"):79,("nissan","versa"):77,
    ("nissan","frontier"):82,("nissan","sentra"):78,("nissan","xtrail"):76,
    ("nissan","x-trail"):76,("nissan","tiida"):75,
    ("honda","crv"):90,("honda","cr-v"):90,("honda","civic"):91,
    ("honda","pilot"):84,("honda","fit"):88,("honda","hr-v"):87,("honda","hrv"):87,
    ("mitsubishi","montero sport"):81,("mitsubishi","outlander"):79,
    ("mitsubishi","l200"):82,("mitsubishi","montero"):81,("mitsubishi","asx"):77,
    ("suzuki","grand vitara"):82,("suzuki","vitara"):82,("suzuki","swift"):83,
    ("chevrolet","spark"):72,("isuzu","dmax"):83,("ford","explorer"):69,
    ("jeep","wrangler"):66,
    ("bmw","x5"):60,("bmw","x1"):62,("bmw","x3"):61,
    ("audi","q3"):61,("audi","q5"):60,("land rover","range rover"):52,
}
RELIABILITY_BY_BRAND = {
    "toyota":90,"honda":88,"mazda":83,"suzuki":81,"subaru":82,"lexus":92,
    "mitsubishi":79,"kia":78,"hyundai":79,"nissan":76,"ford":70,"chevrolet":69,
    "volkswagen":68,"jeep":64,"renault":63,"peugeot":62,"fiat":58,
    "land rover":55,"bmw":62,"mercedes-benz":63,"audi":61,
}
RELIABILITY_FLOOR = 65
RESALE_BY_BRAND = {
    "toyota":95,"honda":88,"lexus":90,"subaru":80,"mazda":78,"suzuki":76,
    "mitsubishi":75,"nissan":70,"hyundai":68,"kia":67,"ford":60,"chevrolet":58,
    "volkswagen":60,"bmw":55,"mercedes-benz":57,
}
RESALE_FLOOR = 60
SPACE_BY_BODY = {"suv":88,"pickup":90,"minivan":95,"wagon":85,"crossover":82,
    "sedan":65,"hatchback":55,"coupe":35,"convertible":25}
SPACE_FLOOR = 60
APPEAL_BY_BODY = {"suv":82,"crossover":80,"pickup":78,"coupe":85,"convertible":88,
    "sedan":65,"hatchback":62,"minivan":45,"wagon":55}
APPEAL_FLOOR = 60

# ─────────────────── (11) NORMALIZACION ─────────────────────────────
def _norm(s):
    s = (s or "").strip().lower()
    for a,b in (("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n")):
        s = s.replace(a,b)
    return s

_BODY_CANON = {
    "hatch":"hatchback","hatchback":"hatchback","hb":"hatchback",
    "sedan":"sedan","saloon":"sedan",
    "suv":"suv","sport utility":"suv","todo terreno":"suv","4x4":"suv",
    "crossover":"crossover","cuv":"crossover",
    "pickup":"pickup","pick-up":"pickup","pick up":"pickup","camioneta":"pickup",
    "minivan":"minivan","van":"minivan","minibus":"minivan",
    "wagon":"wagon","station wagon":"wagon","familiar":"wagon",
    "coupe":"coupe","convertible":"convertible","cabrio":"convertible",
}
def canon_body(b):
    b = _norm(b); return _BODY_CANON.get(b, b)
def canon_transmission(t):
    t = _norm(t)
    if t.startswith("auto") or "cvt" in t: return "automatica"
    if t.startswith("man"): return "manual"
    return t
def canon_fuel(f):
    f = _norm(f)
    if f in ("hibrido","hybrid"): return "hibrido"
    if f in ("electrico","electric","ev"): return "electrico"
    if f == "diesel": return "diesel"
    if f in ("gasolina","gas","regular","super"): return "gasolina"
    return f
def canon_model(m):
    return _norm(m)

# ──────────────────────────── PERFIL ───────────────────────────────
@dataclass
class CarlyProfile:
    max_monthly: Optional[float] = None
    max_price: Optional[float] = None
    min_year: Optional[int] = None
    exclude_body: list = field(default_factory=list)
    exclude_transmission: Optional[str] = None
    exclude_brands: list = field(default_factory=list)
    require_body: list = field(default_factory=list)
    w_reliability: float = 0.45
    w_economy: float = 0.30
    w_space: float = 0.30
    w_value: float = 0.50
    w_resale: float = 0.30
    w_appeal: float = 0.20
    w_modernity: float = 0.35
    surprise: bool = False

# ──────────────────────────── FACTORES ─────────────────────────────
def reliability_base(make, model):
    key = (_norm(make), canon_model(model))
    if key in RELIABILITY_BY_MODEL: return RELIABILITY_BY_MODEL[key]
    return RELIABILITY_BY_BRAND.get(_norm(make), RELIABILITY_FLOOR)

def reliability_score(make, model, km):
    base = reliability_base(make, model)
    if km is not None:
        if km < 50000: base += 3
        elif km < 90000: base += 0
        elif km < 130000: base -= 6
        elif km < 180000: base -= 14
        else: base -= 22
    return max(0.0, min(100.0, base))

def resale_score(make): return RESALE_BY_BRAND.get(_norm(make), RESALE_FLOOR)
def space_score(bt): return SPACE_BY_BODY.get(canon_body(bt), SPACE_FLOOR)

def appeal_score(bt, year):
    base = APPEAL_BY_BODY.get(canon_body(bt), APPEAL_FLOOR)
    if year:
        age = CURRENT_YEAR - year
        if age <= 3: base += 8
        elif age >= 12: base -= 8
    return max(0.0, min(100.0, base))

def modernity_score(year):
    if not year: return 55.0
    age = CURRENT_YEAR - year
    if age <= 2: return 100.0
    if age <= 4: return 90.0
    if age <= 6: return 78.0
    if age <= 8: return 64.0
    if age <= 10: return 50.0
    if age <= 13: return 35.0
    return 20.0

def economy_score(km, year, fuel_type):
    f = canon_fuel(fuel_type)
    if f == "electrico": s = 95.0
    elif f == "hibrido": s = 88.0
    elif f == "diesel": s = 70.0
    else: s = 58.0
    if km is not None:
        if km < 40000: s += 12
        elif km < 80000: s += 6
        elif km < 130000: s -= 2
        elif km < 180000: s -= 10
        else: s -= 18
    if year:
        age = CURRENT_YEAR - year
        if age <= 4: s += 6
        elif age >= 13: s -= 8
    return max(0.0, min(100.0, s))

def value_score(price, comps):
    valid = [p for p in comps if p and p > 0]
    if not price or len(valid) < 3:
        return 60.0, None, "precio de referencia"
    avg = sum(valid)/len(valid)
    if avg <= 0: return 60.0, None, "precio de referencia"
    ratio = price/avg
    delta_pct = round((ratio-1.0)*100, 1)
    s = max(0.0, min(100.0, 60.0 + (1.0-ratio)*150.0))
    if delta_pct <= -8: label = "bajo el mercado"
    elif delta_pct >= 8: label = "sobre el mercado"
    else: label = "en precio de mercado"
    return s, delta_pct, label

# ──────────────────────────── FILTRO ───────────────────────────────
def passes_filters(car, p: CarlyProfile):
    m = car.get("monthly_est")
    if p.max_monthly is not None and m is not None and m > p.max_monthly: return False
    pr = car.get("price_usd")
    if p.max_price is not None and pr is not None and pr > p.max_price: return False
    y = car.get("year")
    if p.min_year is not None and y is not None and y < p.min_year: return False
    bt = canon_body(car.get("body_type"))
    req = [canon_body(b) for b in p.require_body]
    if req and bt not in req: return False
    if bt in [canon_body(b) for b in p.exclude_body]: return False
    if p.exclude_transmission and \
       canon_transmission(car.get("transmission")) == canon_transmission(p.exclude_transmission):
        return False
    if _norm(car.get("make")) in [_norm(b) for b in p.exclude_brands]: return False
    return True

# ──────────────────────────── SCORING ──────────────────────────────
def score_car(car, p: CarlyProfile, comps_by_model):
    make, model = car.get("make"), car.get("model")
    km, year = car.get("km"), car.get("year")
    comps = comps_by_model.get((_norm(make), canon_model(model)), [])
    v_score, v_delta, v_label = value_score(car.get("price_usd"), comps)
    factors = {
        "reliability": reliability_score(make, model, km),
        "economy": economy_score(km, year, car.get("fuel_type")),
        "space": space_score(car.get("body_type")),
        "value": v_score,
        "resale": resale_score(make),
        "appeal": appeal_score(car.get("body_type"), year),
        "modernity": modernity_score(year),
    }
    weights = {
        "reliability": p.w_reliability, "economy": p.w_economy, "space": p.w_space,
        "value": p.w_value, "resale": p.w_resale, "appeal": p.w_appeal,
        "modernity": p.w_modernity,
    }
    wsum = sum(weights.values()) or 1.0
    total = sum(factors[k]*weights[k] for k in factors)/wsum
    return round(total,1), factors, {"value_delta_pct": v_delta, "value_label": v_label}

# ──────────────── (8) CONTRA + (9) INSPECCION ──────────────────────
def honest_caveat(car, factors):
    km = car.get("km")
    if factors["modernity"] < 50:
        return "No es de los mas nuevos, pero bien cuidado puede dar muchos kilometros tranquilos."
    if km and km > 130000:
        return "Tiene bastante kilometraje; vale una buena revision mecanica antes de cerrar."
    if factors["appeal"] < 55:
        return "No es el mas vistoso, pero gana en sentido practico."
    if factors["economy"] < 60:
        return "El consumo no es su fuerte; tenelo en cuenta si haces muchos kilometros."
    if factors["resale"] < 62:
        return "Su reventa es algo mas baja que un Toyota o Honda; importa si lo cambias pronto."
    return "Opcion equilibrada, sin peros importantes para lo que buscas."

def inspection_focus(car):
    year, km = car.get("year"), car.get("km")
    age = CURRENT_YEAR - year if year else 0
    pts = []
    if km and km > 120000: pts += ["transmision","suspension"]
    if age >= 8: pts += ["historial de mantenimiento","fugas de aceite"]
    if canon_fuel(car.get("fuel_type")) == "hibrido" and age >= 6:
        pts += ["estado de la bateria hibrida"]
    if not pts: pts = ["estado general y documentos al dia"]
    seen = []
    for x in pts:
        if x not in seen: seen.append(x)
    return seen[:3]

# ──────────────────── RANKING + (4) DIVERSIDAD ─────────────────────
def best_for_label(factors):
    ejes = {"reliability":"Tranquilidad","economy":"Ahorro","space":"Familia",
            "value":"Mejor precio","resale":"Inversion","appeal":"Estilo",
            "modernity":"Lo mas nuevo"}
    return ejes.get(max(factors, key=factors.get), "Balance")

def rank_cars(cars, profile: CarlyProfile, top_n=5):
    comps_by_model = {}
    for c in cars:
        key = (_norm(c.get("make")), canon_model(c.get("model")))
        comps_by_model.setdefault(key, []).append(c.get("price_usd"))

    survivors = [c for c in cars if passes_filters(c, profile)]
    scored = []
    for c in survivors:
        total, factors, meta = score_car(c, profile, comps_by_model)
        scored.append({
            "car": c, "score": total, "factors": factors,
            "value_delta_pct": meta["value_delta_pct"], "value_label": meta["value_label"],
            "best_for": best_for_label(factors),
            "caveat": honest_caveat(c, factors),
            "inspect": inspection_focus(c),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)

    # (4) diversidad: evita clones make+body
    top, seen = [], set()
    for e in scored:
        c = e["car"]; combo = (_norm(c.get("make")), canon_body(c.get("body_type")))
        if combo in seen: continue
        top.append(e); seen.add(combo)
        if len(top) >= top_n: break
    if len(top) < top_n:
        for e in scored:
            if e not in top:
                top.append(e)
                if len(top) >= top_n: break

    # (prompt 5) sorpresa
    if profile.surprise and len(scored) > len(top):
        bodies = {canon_body(x["car"].get("body_type")) for x in top}
        for cand in scored:
            if cand in top: continue
            if canon_body(cand["car"].get("body_type")) not in bodies:
                top[-1] = {**cand, "surprise": True}; break

    return top
